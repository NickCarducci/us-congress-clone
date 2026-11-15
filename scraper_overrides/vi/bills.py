"""U.S. Virgin Islands bills, from the Legislature's rebuilt bill tracker.

Overrides openstates-scrapers' scrapers/vi/bills.py (copied in by
state-bill-watcher.yml): the tracker's JSON API on port 8082 no longer
answers; the site now serves HTML (a Django app). The bill list is a form POST
to / (csrfmiddlewaretoken, legno=<Legislature>, pageno=<n>, ten bills a page,
data-total-pages on the first page); each bill's page, /bill_detail/<id>/,
has its numbers, subject, dated status history and sponsors.
"""
import re

import dateutil.parser
import lxml.html
from openstates.scrape import Bill, Scraper

BASE = "https://billtracking.legvi.org"

# Status history, as the tracker names it -> Open States action classification.
ACTIONS = {
    "received": [],
    "assigned": [],
    "to senator": [],
    "introduced": ["introduction"],
    "committee": ["referral-committee"],
    "rules": ["referral-committee"],
    "floor action": [],
    "to governor": ["executive-receipt"],
    "to lt. governor": ["executive-receipt"],
    "approved": ["executive-signature"],
    "enacted": ["became-law"],
    "vetoed": ["executive-veto"],
    "overridden": ["veto-override-passage"],
}


def text(node):
    return re.sub(r"\s+", " ", node.text_content()).strip() if node is not None else ""


class VIBillScraper(Scraper):
    def scrape(self, session=None):
        page = self.get(f"{BASE}/")
        token = lxml.html.fromstring(page.content).xpath("//input[@name='csrfmiddlewaretoken']/@value")
        token = token[0] if token else ""
        seen = set()
        pageno, total = 1, 1
        while pageno <= total:
            response = self.post(
                f"{BASE}/",
                data={"csrfmiddlewaretoken": token, "sort": "lastaction", "order": "desc",
                      "pageno": str(pageno), "legno": str(session), "universal_search": ""},
                headers={"Referer": f"{BASE}/"},
            )
            doc = lxml.html.fromstring(response.content)
            if pageno == 1:
                pages = doc.xpath("//*[@data-total-pages]/@data-total-pages")
                total = int(pages[0]) if pages and pages[0].isdigit() else 1
            for href in doc.xpath("//a[starts-with(@href, '/bill_detail/')]/@href"):
                if href not in seen:
                    seen.add(href)
                    yield from self.scrape_bill(session, f"{BASE}{href}")
            pageno += 1

    def scrape_bill(self, session, url):
        doc = lxml.html.fromstring(self.get(url).content)
        tables = doc.xpath("//table[contains(@class, 'bill-table')]")
        numbers = {}
        for table in tables:
            heads = [text(th) for th in table.xpath(".//thead//th")]
            if "Bill No." in heads:
                cells = table.xpath(".//tbody/tr[1]/td")
                numbers = {head: text(cell) for head, cell in zip(heads, cells)}
                break
        identifier = numbers.get("Bill No.") or numbers.get("Resolution No.")
        if not identifier:
            return
        page_text = text(doc)
        subject = re.search(r"Subject:\s*(.+?)\s+Introduced\b", page_text)
        title = subject.group(1) if subject else identifier
        resolution = (not numbers.get("Bill No.") and numbers.get("Resolution No.")) \
            or title.lower().startswith("a resolution")
        bill = Bill(identifier=identifier, legislative_session=session, chamber="legislature",
                    title=title, classification="resolution" if resolution else "bill")
        bill.add_source(url)
        if numbers.get("Act No."):
            bill.extras["act_number"] = numbers["Act No."]

        for row in doc.xpath("//td[contains(@class, 'status-cell')]/.."):
            status = text(row.xpath(".//td[contains(@class, 'status-cell')]")[0])
            date = text((row.xpath(".//td[contains(@class, 'date-cell')]") or [None])[0])
            if not status or not date:
                continue
            try:
                when = dateutil.parser.parse(date).date()
            except (ValueError, OverflowError):
                continue
            committee = text((row.xpath(".//td[contains(@class, 'committee-cell')]") or [None])[0])
            description = text((row.xpath(".//td[contains(@class, 'description-cell')]") or [None])[0])
            label = status
            if description and description.lower() != "none":
                label = f"{status}: {description}"
            action = bill.add_action(label, when, chamber="legislature",
                                     classification=ACTIONS.get(status.lower(), []))
            if committee and committee.lower() != "none":
                action.add_related_entity(committee, "organization")
            for link in row.xpath(".//td[contains(@class, 'document-cell')]//a[@href]"):
                bill.add_document_link(text(link) or status, link.get("href") if link.get("href").startswith("http")
                                       else f"{BASE}{link.get('href')}", on_duplicate="ignore")

        for row in doc.xpath("//div[contains(@class, 'sponsors')]//tbody/tr"):
            cells = [text(td) for td in row.xpath("./td")]
            if len(cells) >= 2 and cells[0]:
                primary = cells[1].lower().startswith("primary")
                bill.add_sponsorship(cells[0], "primary" if primary else "cosponsor", "person", primary=primary)

        for link in doc.xpath("//a[starts-with(@href, '/pdf/')]"):
            label = text(link)
            if label == identifier or label == numbers.get("Act No."):
                bill.add_version_link(f"{'Act' if label == numbers.get('Act No.') else 'Bill'} {label}",
                                      f"{BASE}{link.get('href')}", media_type="application/pdf",
                                      on_duplicate="ignore")
        yield bill
