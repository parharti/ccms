"""
Builds demo data for the roster-only flow:

  demo/DIC_Demo_Roster.xlsx   a roster laid out like the DIC sheet (title row,
                              header row, one row per candidate, a hyperlink in
                              the Resume column)
  demo/files/resumes/*.pdf    one resume per candidate
  demo/files/login.html       what a login-walled resume link returns

Serve the links with:   python demo/serve.py     (http://127.0.0.1:8766)
Then upload DIC_Demo_Roster.xlsx on the candidate-upload step.

The candidates are written against a Data Analyst post (about 5 years of
analytics experience required, BI / SQL / Python skills, age limit 21-35) and
cover every outcome of the screening rules -- see EXPECTED below.
"""

import os
import sys
from datetime import date

import openpyxl
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "files")
RESUMES = os.path.join(FILES, "resumes")
BASE_URL = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8766")

# (name, father, dob, category, email, phone, grad degree, grad institute, grad marks, grad year,
#  jobs [(org, designation, start, end, salary)], skills, resume link kind, expectation)
# end None = still working there.
D = date
CANDIDATES = [
    ("Mr. Aarav Mehta", "Rakesh Mehta", D(1994, 3, 12), "gen", "aarav.mehta@example.com", "9810000001",
     "B.Tech", "NIT Surat", 78, 2016,
     [("Tata Insights", "Senior Data Analyst", D(2019, 7, 1), None, 1100000),
      ("Flipkart", "Data Analyst", D(2016, 7, 1), D(2019, 6, 15), 600000)],
     "SQL, Python, Power BI, Tableau, Excel, dashboards, ETL, statistics, A/B testing",
     "ok", "ELIGIBLE: 10 yrs analytics, all skills"),
    ("Ms. Diya Nair", "Suresh Nair", D(1996, 8, 5), "gen", "diya.nair@example.com", "9810000002",
     "B.Sc Statistics", "Pune University", 74, 2017,
     [("Zensar", "BI Developer", D(2022, 10, 1), None, 900000),
      ("Infosys", "Reporting Analyst", D(2018, 6, 1), D(2022, 9, 15), 500000)],
     "Power BI, DAX, SQL, Tableau, Python, Excel, data modelling, dashboards, reporting",
     "ok", "ELIGIBLE: 8 yrs reporting/BI"),
    ("Mr. Kabir Singh", "Harpreet Singh", D(1997, 1, 20), "obc", "kabir.singh@example.com", "9810000003",
     "B.Tech", "Delhi Technological University", 72, 2019,
     [("Paytm", "Data Analyst", D(2022, 10, 1), None, 1000000)],
     "SQL, Python, Power BI, Looker, Tableau, dashboards, Excel, pandas, KPI reporting, A/B testing",
     "ok", "EXCEPTION: ~4 yrs analytics (1 yr short), strong skills -> Strong candidate, with exception"),
    ("Ms. Isha Verma", "Anil Verma", D(1998, 11, 2), "gen", "isha.verma@example.com", "9810000004",
     "B.Sc IT", "Mumbai University", 70, 2020,
     [("Capgemini", "Data Analyst", D(2022, 12, 1), None, 800000)],
     "SQL, Power BI, Tableau, Python, Excel, dashboards, statistics, ETL, data cleaning, reporting",
     "ok", "EXCEPTION: ~3.8 yrs analytics (1.2 yrs short), strong skills"),
    ("Mr. Rohan Das", "Biswajit Das", D(1999, 4, 17), "sc", "rohan.das@example.com", "9810000005",
     "B.Com", "Calcutta University", 65, 2020,
     [("Local Retail Pvt Ltd", "MIS Executive", D(2022, 10, 1), None, 360000),
      ("Kolkata Traders", "Accounts Assistant", D(2020, 7, 1), D(2022, 9, 1), 240000)],
     "Excel, Tally, basic SQL, reporting",
     "ok", "NOT ELIGIBLE or review: ~4 yrs but weak skills"),
    ("Ms. Sana Khan", "Imran Khan", D(2000, 2, 9), "gen", "sana.khan@example.com", "9810000006",
     "MCA", "Jamia Millia Islamia", 81, 2023,
     [("Startup Labs", "Data Analyst Intern", D(2026, 1, 5), None, 20000)],
     "Python, SQL, Power BI, Tableau, dashboards, machine learning, pandas, statistics",
     "ok", "NOT ELIGIBLE: ~9 months experience despite strong skills"),
    ("Mr. Vikram Rao", "Srinivas Rao", D(1984, 6, 30), "gen", "vikram.rao@example.com", "9810000007",
     "B.Tech", "JNTU Hyderabad", 68, 2006,
     [("Deloitte", "Lead Data Analyst", D(2014, 1, 1), None, 2200000),
      ("Accenture", "Analyst", D(2007, 1, 1), D(2013, 12, 15), 700000)],
     "SQL, Power BI, Tableau, Python, dashboards, ETL, data warehousing, stakeholder reporting",
     "ok", "NOT ELIGIBLE: over the age limit (born 1984)"),
    ("Ms. Neha Kulkarni", "Prakash Kulkarni", D(1995, 12, 3), "gen", "neha.kulkarni@example.com", "9810000008",
     "BBA", "Symbiosis Pune", 71, 2017,
     [("HDFC Bank", "Customer Service Officer", D(2017, 8, 1), D(2023, 6, 30), 400000),
      ("Cafe Brew", "Store Manager", D(2023, 7, 15), None, 420000)],
     "Customer service, Excel, communication, team management",
     "ok", "NOT ELIGIBLE: 9 yrs experience but none in analytics"),
    ("Mr. Arjun Pillai", "Gopal Pillai", D(1993, 9, 14), "obc", "arjun.pillai@example.com", "9810000009",
     "M.Sc Data Science", "IIIT Bangalore", 83, 2018,
     [("Mu Sigma", "Decision Scientist", D(2018, 7, 1), None, 1400000)],
     "SQL, Python, Power BI, Tableau, R, machine learning, dashboards, statistics, A/B testing",
     "none", "ELIGIBLE from the sheet; NO resume link -> review once the fetch finds none"),
    ("Ms. Pooja Iyer", "Venkat Iyer", D(1996, 5, 22), "gen", "pooja.iyer@example.com", "9810000010",
     "B.E.", "VTU Bangalore", 75, 2018,
     [("Mindtree", "Data Analyst", D(2018, 7, 1), None, 950000)],
     "SQL, Power BI, Python, Tableau, dashboards, Excel, reporting",
     "login", "Resume link returns a login page -> review after the fetch"),
    ("Mr. Tarun Joshi", "Mahesh Joshi", D(1995, 7, 8), "gen", "tarun.joshi@example.com", "9810000011",
     "B.Tech", "BITS Pilani", 77, 2017,
     [("Swiggy", "Senior Analyst", D(2017, 7, 1), None, 1300000)],
     "SQL, Python, Power BI, Looker, dashboards, A/B testing, KPI reporting, Excel",
     "dead", "Resume link is dead (404) -> review after the fetch"),
    ("Ms. Ananya Bose", "Subrata Bose", D(1992, 10, 25), "gen", "ananya.bose@example.com", "9810000012",
     "M.Tech", "IIT Kharagpur", 85, 2016,
     [("Amazon", "Business Intelligence Engineer", D(2018, 8, 1), None, 2400000),
      ("Cognizant", "Data Analyst", D(2016, 7, 1), D(2018, 7, 15), 600000)],
     "SQL, Power BI, Tableau, Python, dashboards, ETL, data modelling, statistics, AWS, A/B testing",
     "ok", "ELIGIBLE: 10 yrs, top skills"),
]

TITLE = "Data Analyst, Dashboards & Reports"
HEADERS = [
    "S. No", "Candidate Name", "Father Name", "DOB", "Age on(21-12-2025)", "Category", "Email", "Phone",
    "State choice 1", "State choice 2", "State choice 3",
    "10th Degree", "10th Institute", "10th Marks", "10th Year", "10th Subject",
    "12th Degree", "12th Institute", "12th Marks", "12th Year", "12th Subject",
    "Graduation Degree", "Graduation Institute", "Graduation Marks", "Graduation Year", "Graduation Subject",
    "Experience Details", "Total Experience", "Ref1", "Ref2", "Address", "Resume", "Remarks",
]

LINK_FOR = {
    "login": f"{BASE_URL}/login.html",
    "dead": f"{BASE_URL}/resumes/this-file-does-not-exist.pdf",
}


def slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name.replace("Mr. ", "").replace("Ms. ", "")).strip("-")


def fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def experience_text(jobs) -> str:
    out = ""
    for org, desig, start, end, salary in jobs:
        out += f"Org: {org} || Dsgn: {desig} || Duration: {fmt(start)} to {fmt(end or date.today())} || Salary: {salary} ||||"
    return out


def total_experience(jobs) -> str:
    days = sum(((end or date.today()) - start).days for _, _, start, end, _ in jobs)
    years, rem = divmod(days, 365)
    months, d = divmod(rem, 30)
    return f"{years:02d} year(s)||{months:02d} month(s)||{d:02d} day(s)"


def age_text(dob: date) -> str:
    ref = date(2025, 12, 21)
    years = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return f"{years} year(s)"


def write_resume(path: str, c) -> None:
    name, _, dob, _, email, phone, degree, institute, marks, year, jobs, skills = c[:12]
    lines = [name.replace("Mr. ", "").replace("Ms. ", ""), f"{email}  |  {phone}", "", "PROFESSIONAL SUMMARY"]
    in_analytics = [j for j in jobs if any(k in j[1].lower() for k in ("analyst", "bi ", "intelligence", "scientist", "developer"))]
    lines.append(
        f"Data professional with hands-on experience in {', '.join(skills.split(', ')[:4])}."
        if in_analytics else
        "Operations professional looking to move into a data-focused role."
    )
    lines += ["", "EXPERIENCE"]
    for org, desig, start, end, _ in jobs:
        lines.append(f"{desig}, {org}  ({start.strftime('%b %Y')} - {end.strftime('%b %Y') if end else 'Present'})")
        if "analyst" in desig.lower() or "intelligence" in desig.lower() or "scientist" in desig.lower() or "bi " in desig.lower():
            lines.append("  - Built and maintained dashboards and recurring reports for business teams.")
            lines.append("  - Wrote SQL queries and Python scripts to clean, join and analyse large datasets.")
        else:
            lines.append("  - Handled day-to-day operations, customer queries and basic spreadsheet reporting.")
    lines += ["", "SKILLS", skills, "", "EDUCATION", f"{degree}, {institute}  ({year})  -  {marks}%"]
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(54, 54, 540, 790), "\n".join(lines), fontsize=11, fontname="helv")
    doc.save(path)


def main() -> None:
    os.makedirs(RESUMES, exist_ok=True)
    with open(os.path.join(FILES, "login.html"), "w", encoding="utf-8") as f:
        f.write("<html><body><h1>Sign in to view this document</h1><form><input name='user'><input type='password'></form></body></html>")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([TITLE])
    ws.append(HEADERS)

    expectations = []
    for i, c in enumerate(CANDIDATES, start=1):
        name, father, dob, category, email, phone, degree, institute, marks, year, jobs, skills, kind, expect = c
        row = [
            i, name, father, dob, age_text(dob), category, email, phone, None, None, None,
            "10th", "State Board", 75, year - 6, "All", "12th", "State Board", 70, year - 4, "Science",
            degree, institute, marks, year, "Data / Computer Science" if "Data" in degree or "IT" in degree else degree,
            experience_text(jobs), total_experience(jobs),
            f"Name: Referee One || Email: ref1.{i}@example.com || Mobile: 9000000001",
            f"Name: Referee Two || Email: ref2.{i}@example.com || Mobile: 9000000002",
            "Demo address, India", "Resume" if kind != "none" else None, None,
        ]
        ws.append(row)
        excel_row = ws.max_row
        ws.cell(row=excel_row, column=4).number_format = "yyyy-mm-dd"

        if kind == "ok":
            resume_file = f"{i:02d}-{slug(name)}.pdf"
            write_resume(os.path.join(RESUMES, resume_file), c)
            ws.cell(row=excel_row, column=32).hyperlink = f"{BASE_URL}/resumes/{resume_file}"
        elif kind in LINK_FOR:
            if kind == "login":
                write_resume(os.path.join(RESUMES, f"{i:02d}-{slug(name)}.pdf"), c)
            ws.cell(row=excel_row, column=32).hyperlink = LINK_FOR[kind]
        expectations.append((i, name, expect))

    path = os.path.join(HERE, "DIC_Demo_Roster.xlsx")
    wb.save(path)
    print(f"Wrote {path} ({len(CANDIDATES)} candidates) and {len(os.listdir(RESUMES))} resume PDFs")
    print("\nWhat each demo candidate is meant to show:")
    for i, name, expect in expectations:
        print(f"  {i:2d}. {name:22s} {expect}")


if __name__ == "__main__":
    sys.exit(main())
