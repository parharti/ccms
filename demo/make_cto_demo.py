"""
CTO demo pack: one JD + a 10-candidate roster that together show every
screening outcome and tag the product has.

  demo/cto/JD - Data Analyst (Dashboards & Reports) - Demo.docx   upload on "New post"
  demo/cto/CTO_Demo_Roster.xlsx                                    upload as roster (DIC layout)
  demo/cto/CTO_Demo_Answer_Key.xlsx                                what each row should show (do NOT upload)
  demo/files/cto/resumes/*.pdf                                     resumes behind the roster links

Run:   backend/venv/Scripts/python.exe demo/make_cto_demo.py
Serve: backend/venv/Scripts/python.exe demo/serve.py   (keeps http://127.0.0.1:8766 up for the resume fetch)

Dates are computed for screening on or after 13-Nov-2026 (the app uses
today's date for age and "present" job durations).
"""

import os
from datetime import date

import docx
import openpyxl
import pymupdf
from docx.shared import Pt
from openpyxl.styles import Alignment, Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cto")
RESUMES = os.path.join(HERE, "files", "cto", "resumes")
BASE_URL = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8766")
TODAY = date(2026, 11, 13)
D = date

# ---------------------------------------------------------------------------
# JD -- same shape and wording style as the real DIC JD, plus an age limit,
# an age-relaxation table and desirable items so every rule is exercised.
# ---------------------------------------------------------------------------
JD_TITLE = "Job Description: Data Analyst, Dashboards & Reports"
JD_INTRO = (
    "Required a skilled Data Analyst with expertise in Python scripting, database query optimization, "
    "cloud technologies, version control and BI tools. The candidate will be responsible for data "
    "extraction, transformation, visualization, automation, and performance optimization to support "
    "strategic business decisions with the following key responsibilities:"
)
JD_RESPONSIBILITIES = [
    "Develop and maintain interactive dashboards and reports using BI tools (Power BI, Tableau, Looker).",
    "Identify key performance indicators (KPIs) and design metrics for business performance tracking.",
    "Develop Python scripts for data manipulation, cleaning, and transformation.",
    "Automate repetitive tasks such as data extraction, API integration, and reporting.",
    "Implement ETL (Extract, Transform, Load) pipelines for data ingestion and transformation.",
    "Write and optimize complex SQL queries for efficient data retrieval.",
    "Work with relational (MySQL, PostgreSQL, SQL Server) and NoSQL (MongoDB, Cassandra) databases.",
    "Work with cloud platforms such as AWS, GCP, or Azure for data storage and processing.",
    "Utilize cloud-based data warehousing solutions (e.g., Snowflake, BigQuery, Redshift).",
    "Use Git/GitHub/GitLab for version control and collaborative development.",
    "Develop and deploy automated reports for stakeholders.",
    "Analyze large datasets to extract trends and generate actionable business insights.",
]
JD_SKILLS = [
    "Python – Strong scripting skills for data processing and automation.",
    "SQL Query Optimization – Experience in improving query performance and database efficiency.",
    "Power BI – Dashboards and reports.",
    "Tableau – Visualization and storytelling.",
    "Cloud Platforms – AWS, GCP, or Azure for data storage, processing, and automation.",
    "Version Control – Proficiency in Git/GitHub/GitLab for collaborative work.",
    "ETL & Data Pipelines – Building automated workflows for data processing.",
    "API Integration – Working with RESTful APIs for data extraction and automation.",
    "Data Warehouses – BigQuery, Redshift, or Snowflake.",
    "NoSQL databases – MongoDB, Cassandra, or DynamoDB.",
    "Workflow Automation – Apache Airflow.",
    "Effective communication and data storytelling for non-technical stakeholders.",
    "Strong analytical and problem-solving abilities; attention to detail and data accuracy.",
]
JD_ESSENTIAL = [
    "Minimum 5 years of experience as a data analyst, BI / visualization developer, Python scripting for data, or similar work.",
    "Bachelor's degree in Computer Science, Information Technology, Data Science, Statistics, Mathematics, or a related field.",
]
JD_DESIRABLE = [
    "Desirable: Master's degree in Data Science, Statistics, Computer Science, or MBA (Business Analytics).",
    "Desirable: Professional certification in Power BI (Microsoft PL-300), Tableau, or a cloud platform (AWS / Azure / GCP).",
]
JD_AGE = "Age limit: 21 to 35 years as on the date of screening."
JD_RELAXATION = [
    ("Category", "Age relaxation"),
    ("Scheduled Caste (SC)", "5 years"),
    ("Scheduled Tribe (ST)", "5 years"),
    ("OBC (Non-Creamy Layer)", "3 years"),
    ("Persons with Disabilities (PwD)", "10 years"),
    ("Ex-Servicemen", "Period of military service plus 3 years"),
]


def write_jd(path: str) -> None:
    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading(JD_TITLE, level=1)
    d.add_paragraph(JD_INTRO)
    for line in JD_RESPONSIBILITIES:
        d.add_paragraph(line, style="List Bullet")
    d.add_paragraph().add_run("Required Skill Set:").bold = True
    for line in JD_SKILLS:
        d.add_paragraph(line, style="List Bullet")
    d.add_paragraph().add_run("Required Experience and Qualification (Essential):").bold = True
    for line in JD_ESSENTIAL:
        d.add_paragraph(line, style="List Bullet")
    d.add_paragraph().add_run("Desirable:").bold = True
    for line in JD_DESIRABLE:
        d.add_paragraph(line, style="List Bullet")
    d.add_paragraph().add_run("Age Limit:").bold = True
    d.add_paragraph(JD_AGE)
    d.add_paragraph().add_run("Age Relaxation (applies as per Government of India norms):").bold = True
    table = d.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for a, b in JD_RELAXATION:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = a, b
    d.save(path)


# ---------------------------------------------------------------------------
# Candidates. Each one is built to show one (or more) rules.
#   sheet_jobs  -> what the candidate DECLARED on the roster
#   resume_jobs -> what the resume says (differs only for the mismatch case)
#   link        -> "ok" (real resume) | "login" (login page instead of a PDF)
# ---------------------------------------------------------------------------
C = [
    dict(
        name="Mr. Aarav Mehta", father="Rakesh Mehta", dob=D(1995, 3, 12), cat="gen",
        degree="M.Tech", institute="IIIT Bangalore", marks=82, year=2018, subject="Data Science",
        ug=("B.Tech Computer Science", "NIT Surat", 2016),
        sheet_jobs=[("Swiggy", "Senior Data Analyst", D(2021, 4, 1), None, 2200000),
                    ("Flipkart", "Data Analyst", D(2018, 7, 1), D(2021, 3, 31), 900000)],
        skills="Python (Pandas, NumPy), SQL query optimisation (indexing, partitioning), Power BI, Tableau, AWS (Redshift, Lambda, S3), Snowflake, Apache Airflow, Git/GitHub, REST API integration, MongoDB, ETL pipelines, data storytelling",
        certs=["Microsoft Certified: Power BI Data Analyst Associate (PL-300), 2022",
               "AWS Certified Data Analytics - Specialty, 2023"],
        link="ok",
        shows="ELIGIBLE - the ideal candidate",
        expect_before="Eligible",
        expect_after="Eligible. Skills ~95-100%, desirable 2/2 (master's + certificates). Highest suitability (~95+). CV certificates listed. No tags.",
        rules="Two-stage check passes; experience sum across 2 jobs (8.6 yrs); desirable items; CV certificate extraction.",
    ),
    dict(
        name="Ms. Meera Krishnan", father="R. Krishnan", dob=D(1993, 7, 21), cat="gen",
        degree="B.Sc", institute="University of Madras", marks=71, year=2015, subject="Statistics",
        ug=None,
        sheet_jobs=[("National Informatics Centre (NIC), MeitY", "Data Analyst", D(2019, 6, 1), None, 1100000),
                    ("Tamil Nadu e-Governance Agency (TNeGA)", "MIS Analyst", D(2016, 7, 1), D(2019, 5, 31), 450000)],
        skills="SQL (PostgreSQL), Python, Tableau, Excel, Git, ETL with Talend, dashboards for government schemes",
        certs=[],
        link="ok",
        shows="ELIGIBLE + GOVERNMENT RELEVANT EXPERIENCE tag",
        expect_before="Eligible + Gov tag",
        expect_after="Eligible + Government Relevant Experience tag. Skills ~45-60% (no Power BI, cloud, warehouse, NoSQL, Airflow). No master's, no certificate. Suitability ~55-65, so she ranks BELOW Aarav: the gov tag is a badge + filter, not a ranking factor.",
        rules="Gov tag needs government employer AND relevant role (both NIC and TNeGA qualify).",
    ),
    dict(
        name="Mr. Rahul Verma", father="Suresh Verma", dob=D(1992, 1, 15), cat="obc",
        degree="B.Tech", institute="Jamia Millia Islamia", marks=74, year=2013, subject="Information Technology",
        ug=None,
        sheet_jobs=[("Mu Sigma", "Data Analyst", D(2019, 8, 1), None, 1500000),
                    ("Ministry of Rural Development, Govt. of India", "Assistant Section Officer", D(2013, 8, 1), D(2019, 7, 31), 600000)],
        skills="Python, SQL, Power BI, Azure (Data Factory, Synapse), Git, REST APIs, ETL pipelines, Excel",
        certs=["Microsoft Certified: Azure Data Fundamentals (DP-900), 2021"],
        link="ok",
        shows="ELIGIBLE - government employer but NOT a relevant role -> NO gov tag",
        expect_before="Eligible",
        expect_after="Eligible, NO gov tag (ministry job is administrative). Experience counts only Mu Sigma (~7.3 yrs); the ministry job is listed as excluded. Skills ~65-75%, certificate desirable met.",
        rules="Experience field rule (unrelated job counts 0); gov tag needs BOTH government AND role-relevant.",
    ),
    dict(
        name="Mr. Kabir Singh", father="Harpreet Singh", dob=D(1998, 1, 20), cat="obc",
        degree="B.Tech", institute="Delhi Technological University", marks=79, year=2020, subject="Computer Science",
        ug=None,
        sheet_jobs=[("Paytm", "Data Analyst", D(2022, 8, 1), None, 1400000)],
        skills="Python (Pandas), SQL query optimisation, Power BI, Tableau, GCP (BigQuery, Cloud Functions), Apache Airflow, Git/GitLab, REST API integration, MongoDB, ETL pipelines, KPI dashboards, stakeholder storytelling",
        certs=["Google Cloud Professional Data Engineer, 2024"],
        link="ok",
        shows="STRONG CANDIDATE WITH EXCEPTION (near-miss on experience, strong skills)",
        expect_before="Needs review - tag 'awaiting resume' (0.7 yr short, skills unknown until resume)",
        expect_after="ELIGIBLE WITH EXCEPTION (own group, between Eligible and Needs review): ~4.3 yrs vs 5 required (0.7 short, within 2-yr tolerance), skills >= 80%.",
        rules="Experience tolerance (2 yrs) + exception skills threshold (80%); awaiting_resume -> strong_exception after fetch.",
    ),
    dict(
        name="Mr. Rohan Das", father="Biswajit Das", dob=D(1996, 4, 17), cat="gen",
        degree="B.Sc", institute="Calcutta University", marks=66, year=2019, subject="Mathematics",
        ug=None,
        sheet_jobs=[("Retail Insights Pvt Ltd", "Junior Data Analyst", D(2023, 4, 1), None, 420000),
                    ("Kolkata Traders", "Accounts Assistant", D(2019, 6, 1), D(2023, 3, 31), 240000)],
        skills="Excel (pivot tables, VLOOKUP), Google Sheets, basic SQL, Tally",
        certs=[],
        link="ok",
        shows="NEAR-MISS but WEAK skills -> NOT ELIGIBLE (+ close miss if HR sets it)",
        expect_before="Needs review - tag 'awaiting resume' (1.4 yrs short)",
        expect_after="Not eligible: only the analyst job counts (~3.6 yrs; accounts job excluded) = 1.4 short, within tolerance, BUT skills well below 80%. Close-miss note only if 'close_miss_experience_min' is set on the post (API only, not in the UI yet).",
        rules="Tolerance alone is not enough - skills must also clear the threshold; field rule; close-miss note.",
    ),
    dict(
        name="Ms. Sana Khan", father="Imran Khan", dob=D(2001, 2, 9), cat="gen",
        degree="MCA", institute="Jamia Millia Islamia", marks=84, year=2025, subject="Computer Applications",
        ug=("BCA", "Jamia Millia Islamia", 2023),
        sheet_jobs=[("Startup Labs", "Data Analyst", D(2026, 2, 2), None, 600000)],
        skills="Python, SQL, Power BI, Tableau, AWS, Git, MongoDB, Airflow, machine learning",
        certs=["Microsoft Certified: Power BI Data Analyst Associate (PL-300), 2025"],
        link="ok",
        shows="9 MONTHS experience, strong profile -> NOT ELIGIBLE",
        expect_before="Not eligible (resume is never fetched)",
        expect_after="Not eligible: ~0.8 yrs vs 5 = 4.2 yrs short, beyond the 2-yr tolerance. Strong skills do not rescue her.",
        rules="Tolerance cap: no exception beyond 2 yrs. Not-eligible candidates are not sent for resume fetch (saves cost).",
    ),
    dict(
        name="Mr. Vikram Rao", father="Srinivas Rao", dob=D(1986, 6, 30), cat="gen",
        degree="B.Tech", institute="JNTU Hyderabad", marks=70, year=2008, subject="Computer Science",
        ug=None,
        sheet_jobs=[("Deloitte", "Lead Data Analyst", D(2014, 1, 1), None, 2800000),
                    ("Accenture", "Data Analyst", D(2008, 7, 1), D(2013, 12, 31), 800000)],
        skills="Python, SQL, Power BI, Tableau, AWS, Snowflake, Airflow, Git",
        certs=[],
        link="ok",
        shows="AGE FAIL (40, General) -> NOT ELIGIBLE with zero AI calls",
        expect_before="Not eligible",
        expect_after="Not eligible: age 40 > 35, General category gets no relaxation. Rule-based, no Gemini call, no suitability score.",
        rules="Age pre-filter runs BEFORE AI.",
    ),
    dict(
        name="Mr. Arjun Pillai", father="Gopal Pillai", dob=D(1989, 9, 14), cat="obc",
        degree="B.Sc", institute="University of Kerala", marks=68, year=2009, subject="Computer Science",
        ug=None,
        sheet_jobs=[("Deloitte", "Data Analyst", D(2019, 3, 1), None, 1600000),
                    ("Genpact", "Reporting Analyst", D(2012, 7, 1), D(2019, 2, 28), 500000)],
        skills="R, Oracle SQL, Qlik Sense, SVN, Informatica (ETL), Google Cloud Platform, Excel, statistics",
        certs=["Qlik Sense Business Analyst Qualification, 2020"],
        link="ok",
        shows="AGE RELAXATION (OBC, 37) + 'RELATED' skills scoring",
        expect_before="Eligible",
        expect_after="Eligible: age 37 > 35 but <= 35 + 3 (OBC relaxation). Skills mostly 'related' (R for Python, Qlik for Power BI/Tableau, SVN for Git) -> 0.5 marks each -> skills ~40-55%.",
        rules="Category relaxation from the JD table; same / related / none marks (1 / 0.5 / 0).",
    ),
    dict(
        name="Ms. Isha Verma", father="Anil Verma", dob=D(1994, 11, 2), cat="gen",
        degree="B.Sc", institute="Mumbai University", marks=72, year=2017, subject="Information Technology",
        ug=None,
        sheet_jobs=[("Capgemini", "Senior Data Analyst", D(2017, 7, 1), None, 1300000)],
        resume_jobs=[("Capgemini", "Data Analyst", D(2022, 6, 1), None),
                     ("Teleperformance", "Customer Support Executive", D(2017, 7, 1), D(2022, 5, 31))],
        skills="Python, SQL, Power BI, Tableau, Azure, Git, ETL, REST APIs",
        certs=[],
        link="ok",
        shows="SHEET vs RESUME MISMATCH -> NEEDS REVIEW",
        expect_before="Eligible (sheet claims 9.4 yrs as analyst)",
        expect_after="Needs review: resume shows analyst only since Jun-2022 (~4.4 yrs); 2017-22 was customer support. Consistency table shows 'inconsistent'. Tag 'Sheet-resume mismatch' (the consistency check is now the only mismatch detector).",
        rules="Resume vs roster consistency check; score not lowered by mismatch.",
    ),
    dict(
        name="Ms. Pooja Iyer", father="Venkat Iyer", dob=D(1995, 5, 22), cat="gen",
        degree="B.E.", institute="VTU Bangalore", marks=76, year=2018, subject="Computer Science",
        ug=None,
        sheet_jobs=[("Mindtree", "Data Analyst", D(2018, 7, 1), None, 1200000)],
        skills="SQL, Power BI, Python, Tableau, Azure, Git, dashboards",
        certs=[],
        link="login",
        shows="RESUME LINK BROKEN (login page) -> MANUAL REVIEW",
        expect_before="Eligible (sheet alone)",
        expect_after="Needs review - tag 'resume unavailable': link returns a login page, not a PDF. HR sees the reason; 'retry failed' re-tries.",
        rules="Resume fetch failure handling.",
    ),
]

TITLE = "Data Analyst, Dashboards & Reports"
HEADERS = [
    "S. No", "Candidate Name", "Father Name", "DOB", "Age on(13-11-2026)", "Category", "Email", "Phone",
    "State choice 1", "State choice 2", "State choice 3",
    "10th Degree", "10th Institute", "10th Marks", "10th Year", "10th Subject",
    "12th Degree", "12th Institute", "12th Marks", "12th Year", "12th Subject",
    "Graduation Degree", "Graduation Institute", "Graduation Marks", "Graduation Year", "Graduation Subject",
    "Experience Details", "Total Experience", "Ref1", "Ref2", "Address", "Resume", "Remarks",
]
RESUME_COL = HEADERS.index("Resume") + 1


def slug(name: str) -> str:
    base = name.replace("Mr. ", "").replace("Ms. ", "")
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in base).strip("-")


def fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def experience_text(jobs) -> str:
    return "".join(
        f"Org: {org} || Dsgn: {desig} || Duration: {fmt(start)} to {fmt(end or TODAY)} || Salary: {salary} ||||"
        for org, desig, start, end, salary in jobs
    )


def total_experience(jobs) -> str:
    days = sum(((end or TODAY) - start).days for _, _, start, end, _ in jobs)
    years, rem = divmod(days, 365)
    months, d = divmod(rem, 30)
    return f"{years:02d} year(s)||{months:02d} month(s)||{d:02d} day(s)"


def age_text(dob: date) -> str:
    years = TODAY.year - dob.year - ((TODAY.month, TODAY.day) < (dob.month, dob.day))
    return f"{years} year(s)"


ANALYTICS_WORDS = ("analyst", "data", "intelligence", "reporting")


def write_resume(path: str, c: dict, email: str, phone: str) -> None:
    jobs = c.get("resume_jobs") or [j[:4] for j in c["sheet_jobs"]]
    lines = [c["name"].replace("Mr. ", "").replace("Ms. ", ""), f"{email}  |  +91 {phone}", "",
             "PROFESSIONAL SUMMARY",
             f"Data professional working with {', '.join(c['skills'].split(', ')[:4])}.", "",
             "EXPERIENCE"]
    for org, desig, start, end in jobs:
        lines.append(f"{desig}, {org}  ({start.strftime('%b %Y')} - {end.strftime('%b %Y') if end else 'Present'})")
        if any(w in desig.lower() for w in ANALYTICS_WORDS):
            lines.append("  - Built and maintained dashboards and recurring reports for business teams.")
            lines.append("  - Wrote SQL and scripts to extract, clean, join and analyse large datasets.")
        else:
            lines.append("  - Handled administrative / customer-facing work and routine spreadsheet tracking.")
    lines += ["", "SKILLS", c["skills"], "", "EDUCATION",
              f"{c['degree']} {c['subject']}, {c['institute']}  ({c['year']})  -  {c['marks']}%"]
    if c.get("ug"):
        deg, inst, yr = c["ug"]
        lines.append(f"{deg}, {inst}  ({yr})")
    lines.append(f"Class XII, State Board ({c['year'] - 4})")
    if c["certs"]:
        lines += ["", "CERTIFICATIONS"] + [f"  - {x}" for x in c["certs"]]
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(54, 54, 540, 800), "\n".join(lines), fontsize=10.5, fontname="helv")
    doc.save(path)


def write_roster(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([TITLE])
    ws.append(HEADERS)
    for i, c in enumerate(C, start=1):
        email = f"{slug(c['name']).replace('-', '.')}@example.com"
        phone = f"98100000{i:02d}"
        ws.append([
            i, c["name"], c["father"], c["dob"], age_text(c["dob"]), c["cat"], email, phone, None, None, None,
            "10th", "State Board", 80, c["year"] - 6 if not c.get("ug") else c["ug"][2] - 6, "All",
            "12th", "State Board", 75, c["year"] - 4 if not c.get("ug") else c["ug"][2] - 4, "Science",
            c["degree"], c["institute"], c["marks"], c["year"], c["subject"],
            experience_text(c["sheet_jobs"]), total_experience(c["sheet_jobs"]),
            f"Name: Referee One || Email: ref1.{i}@example.com || Mobile: 9000000001",
            f"Name: Referee Two || Email: ref2.{i}@example.com || Mobile: 9000000002",
            "Demo address, India", "Resume", None,
        ])
        r = ws.max_row
        ws.cell(row=r, column=4).number_format = "dd-mm-yyyy"
        if c["link"] == "ok":
            file = f"{i:02d}-{slug(c['name'])}.pdf"
            write_resume(os.path.join(RESUMES, file), c, email, phone)
            url = f"{BASE_URL}/cto/resumes/{file}"
        else:
            url = f"{BASE_URL}/login.html"
        # The full link is both the cell text and its hyperlink target.
        link_cell = ws.cell(row=r, column=RESUME_COL)
        link_cell.value, link_cell.hyperlink, link_cell.style = url, url, "Hyperlink"
    ws.column_dimensions[openpyxl.utils.get_column_letter(RESUME_COL)].width = 58
    wb.save(path)


def write_answer_key(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Answer key"
    head = ["#", "Candidate", "What it demonstrates", "After 'Screen' (sheet only)",
            "After 'Fetch resumes' (final)", "Rules exercised"]
    ws.append(head)
    for i, c in enumerate(C, start=1):
        ws.append([i, c["name"], c["shows"], c["expect_before"], c["expect_after"], c["rules"]])
    fill = PatternFill("solid", fgColor="1F3864")
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), fill
    for col, width in zip("ABCDEF", (4, 20, 38, 34, 70, 48)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    s = wb.create_sheet("Demo script")
    steps = [
        "Before the meeting: run demo/serve.py (resume links), start backend + frontend, run the full flow ONCE to check results.",
        "1. New post -> upload 'JD - Data Analyst (Dashboards & Reports) - Demo.docx'. Show: criteria extracted, Must-have vs Desirable, age 21-35 + relaxation table, skill items list.",
        "2. Skill items editor: show weights 1 / 0.5 / 0 and the 'related' mark (0.5).",
        "3. Screening rules card: tolerance 2 yrs, exception skills threshold 80, ranking weights skills 70 / desirable 30 (experience is not scored - it is a must-have with a tolerance).",
        "4. Upload CTO_Demo_Roster.xlsx as roster -> Screen. Show phase-1 results (sheet only): Vikram rejected with no AI call, Sana rejected, Kabir & Rohan 'awaiting resume', Meera already has gov tag.",
        "5. Fetch resumes -> only eligible / needs-review rows are fetched (Sana & Vikram skipped). Show final results.",
        "6. Open Kabir: strong exception reasoning + skill marks table. Open Arjun: related 0.5 marks + OBC relaxation. Open Isha: sheet vs resume table. Open Pooja: resume unavailable reason.",
        "7. Rank by suitability -> groups: Eligible, Eligible with exception, Needs review, Not eligible; suitability decides within a group. Toggle 'Government experience' filter to show Meera.",
        "8. Candidate page -> HR report and Committee brief (print to PDF). Excel export.",
        "9. Change a weight / tolerance -> scores recompute instantly with no new AI call.",
    ]
    for line in steps:
        s.append([line])
    s.column_dimensions["A"].width = 140
    wb.save(path)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(RESUMES, exist_ok=True)
    write_jd(os.path.join(OUT, "JD - Data Analyst (Dashboards & Reports) - Demo.docx"))
    write_roster(os.path.join(OUT, "CTO_Demo_Roster.xlsx"))
    write_answer_key(os.path.join(OUT, "CTO_Demo_Answer_Key.xlsx"))
    print(f"Wrote JD, roster, answer key to {OUT} and {len(os.listdir(RESUMES))} resumes to {RESUMES}")


if __name__ == "__main__":
    main()
