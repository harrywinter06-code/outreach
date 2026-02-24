"""
Streamlit dashboard — the main UI for the internship-hunter system.
Run with: streamlit run dashboard.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from tracker import (
    get_jobs, get_applications, get_companies, get_stats,
    update_job_status, update_application, log_application, upsert_company, update_company,
    get_email_queue, queue_email, approve_email, skip_email, update_queue_item,
    cache_domain_pattern, get_cached_pattern, get_overdue_followups, get_sent_email_for_company,
    count_followups_for_company,
)
from generate import (
    generate_cover_letter, generate_cold_email, generate_linkedin_dm, generate_followup_email,
    parse_cold_email, save_cover_letter_docx, save_outreach, estimate_cost
)
from companies import seed_companies

st.set_page_config(
    page_title="Internship Hunter — Harry Winter",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.metric-card {background:#1e1e2e;padding:12px 16px;border-radius:8px;border:1px solid #313244;}
.stTabs [data-baseweb="tab-list"] {gap: 8px;}
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎯 Internship Hunter")
    st.caption("Harry Winter · Summer 2026")
    st.divider()

    stats = get_stats()
    st.metric("Applications sent", stats["total_applications"])
    st.metric("Pending response", stats["pending_response"])
    st.metric("Interviews", stats["interviews"])
    st.metric("Offers", stats["offers"])
    st.metric("New jobs queued", stats["new_jobs_queued"])
    st.divider()

    if st.button("🔍 Run Job Discovery", use_container_width=True):
        with st.spinner("Scraping Remotive, ATS boards, Reed..."):
            from discover import run_discovery
            result = run_discovery(sources=("remotive", "ats", "reed"))
            st.success(f"Found {result['total_found']} jobs · {result['new_added']} new")

    if st.button("📰 Scan Funding News", use_container_width=True):
        with st.spinner("Parsing Sifted, UKTN, TechCrunch UK..."):
            from discover import fetch_funding_leads
            n = fetch_funding_leads()
            st.success(f"{n} new funding leads added — review in Companies tab")

    if st.button("🏢 Seed Target Companies", use_container_width=True):
        n = seed_companies()
        st.success(f"Loaded {n} target companies")

    if st.button("🔎 Validate ATS Slugs", use_container_width=True):
        with st.spinner("Checking all Greenhouse & Lever boards..."):
            from discover import validate_all_slugs
            r = validate_all_slugs(verbose=False)
            live_gh = sum(1 for v in r["greenhouse"].values() if v == "ok")
            live_lv = sum(1 for v in r["lever"].values() if v == "ok")
            dead = sum(1 for v in {**r["greenhouse"], **r["lever"]}.values() if v == "dead")
            st.success(f"Greenhouse: {live_gh}/{len(r['greenhouse'])} live · Lever: {live_lv}/{len(r['lever'])} live · {dead} dead (cached)")


# ── Tabs ──────────────────────────────────────────────────────────────────────

tabs = st.tabs(["📧 Email Queue", "📥 Jobs", "📋 Applications", "✍️ Generate", "🏢 Companies", "📊 Stats"])


# ── Tab 1: Email Queue ────────────────────────────────────────────────────────

with tabs[0]:
    st.header("Email Queue")
    st.caption("Compose → approve → send. The system handles Gmail. You just review.")

    # ── Compose new email ──────────────────────────────────────────────────────
    with st.expander("➕ Compose new cold email", expanded=False):
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            eq_company  = st.text_input("Company", key="eq_company")
            eq_domain   = st.text_input("Company domain (e.g. wayve.ai)", key="eq_domain")
            eq_contact  = st.text_input("Contact first name", key="eq_contact_first")
            eq_last     = st.text_input("Contact last name", key="eq_contact_last")
        with col_c2:
            eq_role     = st.text_input("Target role / area", placeholder="data / quant / ML engineering", key="eq_role")
            eq_context  = st.text_area("Company context (2-4 sentences — specific, not generic)", height=120, key="eq_context")

        col_btn1, col_btn2 = st.columns(2)

        with col_btn1:
            find_disabled = not (eq_domain and eq_contact and eq_last)
            if st.button("🔍 Find email address", disabled=find_disabled):
                from emailfinder import smart_find, get_domain_pattern, HunterError
                cached_pattern = get_cached_pattern(eq_domain)
                with st.spinner("Looking up email..."):
                    try:
                        hunter_emails = []
                        if not cached_pattern:
                            try:
                                domain_data = get_domain_pattern(eq_domain)
                                if domain_data["pattern"]:
                                    cache_domain_pattern(eq_domain, domain_data["pattern"])
                                    cached_pattern = domain_data["pattern"]
                                hunter_emails = domain_data.get("emails", [])
                            except HunterError:
                                pass
                        # Use Hunter's returned email directly if it matches the entered contact
                        first_lower = eq_contact.lower()
                        last_lower  = eq_last.lower()
                        hunter_hit = next(
                            (e for e in hunter_emails
                             if e.get("first", "").lower() == first_lower
                             and e.get("last", "").lower() == last_lower
                             and e.get("email")),
                            None,
                        )
                        if hunter_hit:
                            st.session_state["eq_found_email"]  = hunter_hit["email"]
                            st.session_state["eq_found_conf"]   = hunter_hit.get("confidence", 70)
                            st.session_state["eq_found_method"] = "hunter_list"
                        else:
                            result = smart_find(eq_contact, eq_last, eq_domain, cached_pattern)
                            st.session_state["eq_found_email"]   = result["email"]
                            st.session_state["eq_found_conf"]    = result["confidence"]
                            st.session_state["eq_found_method"]  = result["method"]
                    except HunterError as e:
                        st.error(str(e))

        if "eq_found_email" in st.session_state:
            conf   = st.session_state["eq_found_conf"]
            method = st.session_state["eq_found_method"]
            colour = "green" if conf >= 70 else "orange" if conf >= 40 else "red"
            st.markdown(f":{colour}[**{st.session_state['eq_found_email']}**  ·  confidence {conf}%  ·  via {method}]")

        with col_btn2:
            gen_disabled = not (eq_company and eq_context and eq_contact)
            if st.button("✍️ Generate email", disabled=gen_disabled, key="eq_gen"):
                with st.spinner("Generating with Claude Sonnet..."):
                    raw, usage = generate_cold_email(
                        eq_company,
                        eq_role or "data/analyst internship",
                        eq_context,
                        eq_contact
                    )
                    subject, body = parse_cold_email(raw)
                    st.session_state["eq_subject"] = subject
                    st.session_state["eq_body"]    = body
                    st.session_state["eq_cost"]    = estimate_cost(usage)

        if "eq_body" in st.session_state:
            word_count = len(st.session_state["eq_body"].split())
            wc_col = "green" if word_count <= 75 else "orange" if word_count <= 90 else "red"
            st.caption(f"~${st.session_state['eq_cost']:.4f} USD  ·  :{wc_col}[{word_count} words]")

            eq_subject_edit = st.text_input("Subject", value=st.session_state["eq_subject"], key="eq_subj_edit")
            eq_body_edit    = st.text_area("Body", value=st.session_state["eq_body"], height=180, key="eq_body_edit")

            to_email = st.text_input(
                "Send to",
                value=st.session_state.get("eq_found_email", ""),
                key="eq_to"
            )

            if st.button("📥 Add to queue", disabled=not to_email, type="primary"):
                conf   = st.session_state.get("eq_found_conf", 0)
                method = st.session_state.get("eq_found_method", "manual")
                queue_email(
                    company=eq_company,
                    contact_name=f"{eq_contact} {eq_last}".strip(),
                    contact_email=to_email,
                    subject=eq_subject_edit,
                    body=eq_body_edit,
                    email_confidence=conf,
                    hunter_method=method,
                )
                # Clear compose state
                for k in ["eq_found_email","eq_found_conf","eq_found_method","eq_subject","eq_body","eq_cost"]:
                    st.session_state.pop(k, None)
                st.success(f"Added to queue → {to_email}")
                st.rerun()

    st.divider()

    # ── Review queue ───────────────────────────────────────────────────────────
    pending = get_email_queue(status="pending")
    approved = get_email_queue(status="approved")
    sent = get_email_queue(status="sent")

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Pending review", len(pending))
    col_m2.metric("Approved / ready", len(approved))
    col_m3.metric("Sent today", sum(1 for e in sent if e.get("sent_at", "").startswith(
        __import__("datetime").date.today().isoformat()
    )))

    if pending:
        st.subheader("Review pending emails")
        for email in pending:
            with st.expander(f"**{email['company']}** → {email['contact_name']}  `{email['contact_email']}`"):
                conf = email.get("email_confidence", 0)
                conf_col = "green" if conf >= 70 else "orange" if conf >= 40 else "red"
                st.caption(f"Email confidence: :{conf_col}[{conf}%]  ·  method: {email.get('hunter_method','?')}")
                st.markdown(f"**Subject:** {email['subject']}")
                st.text(email["body"])
                col_a, col_b, col_e = st.columns([1, 1, 3])
                with col_a:
                    if st.button("✅ Approve", key=f"app_{email['id']}"):
                        approve_email(email["id"])
                        st.rerun()
                with col_b:
                    if st.button("❌ Skip", key=f"skip_{email['id']}"):
                        skip_email(email["id"])
                        st.rerun()

    if approved:
        st.subheader(f"Approved — ready to send ({len(approved)})")
        for email in approved:
            st.markdown(f"- **{email['company']}** → `{email['contact_email']}`  _{email['subject']}_")

        st.divider()

        from config import EMAIL_SEND_DELAY_SECONDS, EMAIL_DAILY_MAX
        est_minutes = (len(approved) * EMAIL_SEND_DELAY_SECONDS) // 60
        st.info(f"Sending {len(approved)} emails with {EMAIL_SEND_DELAY_SECONDS}s gaps → ~{est_minutes} min. Max {EMAIL_DAILY_MAX}/day enforced.")

        if st.button("🚀 Send all approved", type="primary"):
            from sender import send_approved_batch, SendError, check_gmail_connection

            ok, msg = check_gmail_connection()
            if not ok:
                st.error(f"Gmail not connected: {msg}\n\nAdd your App Password to .env")
            else:
                progress_bar = st.progress(0, text="Sending...")
                results_placeholder = st.empty()

                sent_count = [0]
                total = len(approved)

                def on_progress(i, total_n, company):
                    sent_count[0] = i
                    progress_bar.progress(i / total_n, text=f"Sent {i}/{total_n} — last: {company}")

                def on_error(qid, company, err):
                    st.warning(f"Failed: {company} — {err}")

                results = send_approved_batch(on_progress=on_progress, on_error=on_error)
                progress_bar.progress(1.0, text="Done")
                results_placeholder.success(
                    f"Sent: {results['sent']}  ·  Failed: {results['failed']}  ·  "
                    f"Daily limit hit: {results['skipped_daily_limit']}"
                )
                st.rerun()

    elif not pending:
        st.info("Queue is empty. Compose emails above or use the Generate tab.")

    if sent:
        with st.expander(f"Sent history ({len(sent)})"):
            df_sent = pd.DataFrame(sent)[["company", "contact_name", "contact_email", "subject", "sent_at"]]
            st.dataframe(df_sent, use_container_width=True, hide_index=True)


# ── Tab 2: Job Queue ──────────────────────────────────────────────────────────

with tabs[1]:
    st.header("New Jobs to Review")
    col1, col2 = st.columns([3, 1])
    with col2:
        status_filter = st.selectbox("Status", ["new", "shortlisted", "applied", "rejected", "all"], index=0)

    jobs = get_jobs(status=None if status_filter == "all" else status_filter)

    if not jobs:
        st.info("No jobs with this status. Run job discovery from the sidebar.")
    else:
        for job in jobs:
            with st.expander(f"**{job['title']}** — {job['company']}  `{job['location']}`  _{job['source']}_"):
                col_a, col_b, col_c, col_d = st.columns(4)
                with col_a:
                    if st.button("✅ Shortlist", key=f"sl_{job['id']}"):
                        update_job_status(job["id"], "shortlisted")
                        st.rerun()
                with col_b:
                    if st.button("❌ Reject", key=f"rej_{job['id']}"):
                        update_job_status(job["id"], "rejected")
                        st.rerun()
                with col_c:
                    if st.button("✍️ Generate Letter", key=f"gen_{job['id']}"):
                        st.session_state[f"generate_job"] = job
                        st.session_state["active_tab"] = 2
                        st.info("Go to Generate tab →")
                with col_d:
                    if job["url"]:
                        st.link_button("🔗 Open Job", job["url"])

                if job.get("description"):
                    st.caption(job["description"][:500] + "...")
                st.caption(f"Discovered: {job['discovered']}  |  Salary: {job.get('salary') or 'Not listed'}")


# ── Tab 3: Applications Tracker ───────────────────────────────────────────────

with tabs[2]:
    st.header("Application Tracker")

    overdue = get_overdue_followups()
    if overdue:
        st.warning(f"⏰ {len(overdue)} application(s) overdue for follow-up")
        with st.expander("Follow-ups overdue", expanded=True):
            for a in overdue:
                col_fu1, col_fu2, col_fu3 = st.columns([4, 1, 1])
                with col_fu1:
                    st.markdown(
                        f"**{a['company']}** — {a['role']}  "
                        f"_(applied {a['applied_date']}, follow-up due {a['follow_up_date']})_"
                    )
                with col_fu2:
                    if st.button("✉️ Follow-up", key=f"gen_fu_{a['id']}"):
                        original = get_sent_email_for_company(a["company"])
                        contact_email = (original or {}).get("contact_email", "")
                        if not contact_email:
                            st.warning("No sent email found — add follow-up manually in Email Queue.")
                        else:
                            with st.spinner("Generating..."):
                                contact_name = (original or {}).get("contact_name", "") or "there"
                                days_since = (datetime.now() - datetime.strptime(a["applied_date"], "%Y-%m-%d")).days
                                fu_number = min(count_followups_for_company(a["company"]) + 1, 3)
                                raw, _ = generate_followup_email(
                                    a["company"],
                                    contact_name,
                                    (original or {}).get("subject", ""),
                                    days_since,
                                    follow_up_number=fu_number,
                                )
                                subject, body = parse_cold_email(raw)
                                queue_email(
                                    company=a["company"],
                                    contact_name=contact_name,
                                    contact_email=contact_email,
                                    subject=subject or f"Re: {(original or {}).get('subject', 'internship — Harry Winter')}",
                                    body=body,
                                    email_confidence=(original or {}).get("email_confidence", 0),
                                    hunter_method="followup",
                                )
                                next_fu = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                                update_application(a["id"], follow_up_date=next_fu)
                            st.success("Queued → Email Queue tab")
                            st.rerun()
                with col_fu3:
                    if st.button("✓ Done", key=f"fu_{a['id']}"):
                        next_fu = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                        update_application(a["id"], follow_up_date=next_fu)
                        st.rerun()
        st.divider()

    apps = get_applications()
    if not apps:
        st.info("No applications logged yet. Generate a cover letter and log an application from the Generate tab.")
    else:
        df = pd.DataFrame(apps)
        display_cols = ["company", "role", "applied_date", "status", "follow_up_date", "response"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[available],
            use_container_width=True,
            hide_index=True,
            column_config={
                "applied_date": st.column_config.DateColumn("Applied"),
                "follow_up_date": st.column_config.DateColumn("Follow Up"),
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=["applied", "interview", "offer", "rejected", "withdrawn"],
                ),
            }
        )

        st.subheader("Update Application Status")
        app_options = {f"{a['company']} — {a['role']} ({a['applied_date']})": a["id"] for a in apps}
        selected = st.selectbox("Select application", list(app_options.keys()))
        if selected:
            new_status = st.selectbox("New status", ["applied", "interview", "offer", "rejected", "withdrawn"])
            new_notes = st.text_input("Notes / response details")
            if st.button("Update"):
                update_application(app_options[selected], status=new_status, notes=new_notes)
                st.success("Updated")
                st.rerun()


# ── Tab 4: Generate ───────────────────────────────────────────────────────────

with tabs[3]:
    st.header("Generate Cover Letter & Outreach")

    gen_mode = st.radio("Mode", ["From job board (existing job)", "Manual entry"], horizontal=True)

    if gen_mode == "From job board (existing job)":
        shortlisted = get_jobs(status="shortlisted")
        new_jobs = get_jobs(status="new")
        available_jobs = shortlisted + new_jobs
        if not available_jobs:
            st.warning("No shortlisted or new jobs. Discover jobs first.")
            job_id = None
            company_name, role_name, jd_text = "", "", ""
        else:
            job_options = {f"{j['company']} — {j['title']}": j for j in available_jobs}
            selected_key = st.selectbox("Select job", list(job_options.keys()))
            selected_job = job_options[selected_key]
            job_id = selected_job["id"]
            company_name = selected_job["company"]
            role_name = selected_job["title"]
            jd_text = st.text_area("Job description (auto-filled, edit if needed)",
                                   value=selected_job.get("description", ""), height=200)
    else:
        job_id = None
        company_name = st.text_input("Company name")
        role_name = st.text_input("Role title")
        jd_text = st.text_area("Paste job description here", height=200)

    company_context = st.text_area(
        "Company context — specific detail about what they do / recent news / team focus",
        placeholder="e.g. Wayve is building an embodied AI for autonomous vehicles. Their recent Series C focuses on expanding the data engineering team in London.",
        height=80,
    )

    st.divider()

    # ── Cover Letter ──────────────────────────────────────────────────────────
    st.subheader("Cover Letter")
    if st.button("✍️ Generate Cover Letter", type="primary", disabled=not (company_name and role_name and jd_text)):
        with st.spinner("Generating with Claude Sonnet..."):
            letter, usage = generate_cover_letter(company_name, role_name, jd_text, company_context)
            cost = estimate_cost(usage)
            cached = usage.get("cache_read", 0) > 0
            st.session_state["last_letter"] = letter
            st.session_state["last_letter_meta"] = (company_name, role_name, job_id, cost, cached, usage)

    if "last_letter" in st.session_state:
        letter = st.session_state["last_letter"]
        meta = st.session_state["last_letter_meta"]
        company_name_m, role_name_m, job_id_m, cost_m, cached_m, usage_m = meta
        cache_label = "cache hit" if cached_m else "first call"
        st.caption(f"~${cost_m:.4f} USD  ·  {usage_m['input_tokens']} in / {usage_m['output_tokens']} out  ·  {cache_label}")
        edited_letter = st.text_area("Review / edit:", value=letter, height=350, key="letter_edit")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            if st.button("💾 Save as .docx"):
                path = save_cover_letter_docx(company_name_m, role_name_m, edited_letter)
                st.success(f"Saved: {path.name}")
        with col_s2:
            if st.button("📝 Log Application"):
                outreach_saved = st.session_state.get("last_outreach_body", "")
                log_application(job_id_m, company_name_m, role_name_m, edited_letter, outreach_saved)
                if job_id_m:
                    update_job_status(job_id_m, "applied")
                st.success("Logged!")
                del st.session_state["last_letter"]
                st.rerun()
        with col_s3:
            st.download_button("⬇️ Download .txt", edited_letter, file_name=f"cover_{company_name_m}.txt")

    st.divider()

    # ── Outreach ──────────────────────────────────────────────────────────────
    st.subheader("Cold Outreach")
    st.caption("Cold email requires a named contact. LinkedIn DM is shorter and works without a name.")

    outreach_mode = st.radio("Mode", ["Cold email (named contact, with subject line)", "LinkedIn DM"], horizontal=True)
    contact_name = st.text_input(
        "Contact name" + (" — required" if "email" in outreach_mode else " — optional"),
        placeholder="e.g. Sarah"
    )

    disabled_outreach = not (company_name and company_context)
    if "email" in outreach_mode:
        disabled_outreach = disabled_outreach or not contact_name

    if st.button("📩 Generate Outreach", disabled=disabled_outreach):
        with st.spinner("Generating with Claude Sonnet..."):
            if "email" in outreach_mode:
                raw, usage = generate_cold_email(company_name, role_name or "data/analyst internship", company_context, contact_name)
                subject, body = parse_cold_email(raw)
            else:
                body, usage = generate_linkedin_dm(company_name, role_name or "data/analyst internship", company_context, contact_name)
                subject = ""
            cost = estimate_cost(usage)
            st.session_state["last_outreach_subject"] = subject
            st.session_state["last_outreach_body"] = body
            st.session_state["last_outreach_meta"] = (company_name, cost, usage, outreach_mode)

    if "last_outreach_body" in st.session_state:
        subject = st.session_state.get("last_outreach_subject", "")
        body = st.session_state["last_outreach_body"]
        meta_o = st.session_state["last_outreach_meta"]
        company_name_o, cost_o, usage_o, mode_o = meta_o

        st.caption(f"~${cost_o:.4f} USD  ·  {usage_o['input_tokens']} in / {usage_o['output_tokens']} out")

        word_count = len(body.split())
        wc_colour = "green" if word_count <= 75 else "orange" if word_count <= 90 else "red"
        st.caption(f":{wc_colour}[{word_count} words]" + (" ✓ within limit" if word_count <= 75 else " — over target, edit down"))

        if subject:
            edited_subject = st.text_input("Subject line:", value=subject)
            st.session_state["last_outreach_subject"] = edited_subject
        edited_body = st.text_area("Message body:", value=body, height=160, key="outreach_edit")
        st.session_state["last_outreach_body"] = edited_body

        mode_key = "email" if "email" in mode_o else "linkedin"
        if st.button("💾 Save outreach"):
            final_subject = st.session_state.get("last_outreach_subject", "")
            path = save_outreach(company_name_o, final_subject, edited_body, mode=mode_key)
            st.success(f"Saved: {path.name}")


# ── Tab 5: Companies ──────────────────────────────────────────────────────────

with tabs[4]:
    st.header("Target Companies")

    companies = get_companies()
    if not companies:
        st.info("No companies loaded. Click 'Seed Target Companies' in the sidebar.")
    else:
        sector_filter = st.selectbox("Filter by sector", ["All"] + sorted(set(c["sector"] for c in companies if c["sector"])))
        filtered = companies if sector_filter == "All" else [c for c in companies if sector_filter.lower() in c["sector"].lower()]

        df_c = pd.DataFrame(filtered)
        cols = ["name", "sector", "size", "status", "contacted", "has_ucl_alumni", "notes"]
        available_c = [c for c in cols if c in df_c.columns]
        st.dataframe(
            df_c[available_c],
            use_container_width=True,
            hide_index=True,
            column_config={
                "contacted": st.column_config.CheckboxColumn("Contacted"),
                "has_ucl_alumni": st.column_config.CheckboxColumn("UCL Alumni"),
                "notes": st.column_config.TextColumn("Notes", width="large"),
            }
        )

        with st.expander("🎓 Mark UCL alumni presence"):
            st.caption("Companies where a UCL alumnus works get a warm-outbound opener in the generated email (≈30% vs 10% reply rate for cold strangers).")
            ucl_already = [c["name"] for c in filtered if c.get("has_ucl_alumni")]
            ucl_selected = st.multiselect(
                "Companies with a UCL alumnus",
                options=[c["name"] for c in filtered],
                default=ucl_already,
                key="ucl_alumni_select",
            )
            if st.button("Save UCL flags", key="save_ucl_flags"):
                name_to_id = {c["name"]: c["id"] for c in filtered}
                for co in filtered:
                    cid = name_to_id[co["name"]]
                    flag = 1 if co["name"] in ucl_selected else 0
                    if co.get("has_ucl_alumni", 0) != flag:
                        update_company(cid, has_ucl_alumni=flag)
                st.success("UCL alumni flags saved.")
                st.rerun()

        # ── Batch Research ────────────────────────────────────────────────────
        st.divider()
        st.subheader("🔬 Batch Research & Auto-Queue")
        st.caption(
            "Hunter.io → homepage scrape → Claude → email lookup. "
            "Fully resolved companies are auto-queued as pending emails. "
            "Partial results are queued for manual editing. 1 Hunter credit per company."
        )

        uncontacted = [c for c in companies if not c.get("contacted") and c.get("website")]
        selected_names = st.multiselect(
            "Companies to research",
            options=[c["name"] for c in uncontacted],
            default=[],
            help="Uncontacted companies with a website. Recommended: ≤15 per run to stay within Hunter free tier.",
        )

        if selected_names:
            n = len(selected_names)
            st.caption(f"{n} selected · ~{n * 3}s estimated · {n} Hunter credit(s) used")

        if st.button("🔬 Research & auto-queue", type="primary", disabled=not selected_names, key="batch_research_btn"):
            selected_cos = [c for c in companies if c["name"] in selected_names]
            batch_input = [
                {
                    "name": c["name"],
                    "website": c.get("website", ""),
                    "sector": c.get("sector", ""),
                    "notes": c.get("notes", ""),
                    "has_ucl_alumni": bool(c.get("has_ucl_alumni", 0)),
                }
                for c in selected_cos
            ]

            progress_bar = st.progress(0, text="Starting research...")
            status_text = st.empty()

            def _on_progress(i, total, name, result):
                progress_bar.progress(i / total, text=f"{i}/{total} — {name}  [{result.success}]")
                status_text.caption(f"Last: **{name}** · {result.success}  {result.notes or ''}")

            from research import research_batch
            results, credits_exhausted = research_batch(batch_input, on_progress=_on_progress)

            if credits_exhausted:
                st.warning(
                    "Hunter.io monthly credits exhausted mid-batch. "
                    "Remaining companies were not researched. "
                    "Upgrade at hunter.io/users/plan ($34/mo for 500 searches)."
                )

            auto_queued, partial_queued, failed_list = 0, 0, []
            company_id_map = {c["name"]: c["id"] for c in selected_cos}

            for r in results:
                cid = company_id_map.get(r.company)
                if r.success == "full":
                    try:
                        raw, _ = generate_cold_email(
                            r.company,
                            "data / analyst / ML internship",
                            r.context,
                            r.contact_first,
                        )
                        subject, body = parse_cold_email(raw)
                        queue_email(
                            company=r.company,
                            contact_name=f"{r.contact_first} {r.contact_last}".strip(),
                            contact_email=r.contact_email,
                            subject=subject,
                            body=body,
                            email_confidence=r.email_confidence,
                            hunter_method=r.email_method,
                            company_id=cid,
                        )
                        auto_queued += 1
                    except Exception as e:
                        failed_list.append((r.company, f"email generation failed: {e}"))

                elif r.success == "partial" and r.context:
                    queue_email(
                        company=r.company,
                        contact_name=f"{r.contact_first} {r.contact_last}".strip() or "⚠ NEEDS CONTACT",
                        contact_email=r.contact_email or "⚠ NEEDS EMAIL",
                        subject="Internship enquiry — Harry Winter",
                        body=f"[INCOMPLETE — edit contact/email before approving]\n\nResearched context:\n{r.context}",
                        email_confidence=r.email_confidence,
                        hunter_method=r.email_method,
                        company_id=cid,
                    )
                    partial_queued += 1

                else:
                    failed_list.append((r.company, r.notes or "no data found"))

            progress_bar.progress(1.0, text="Done")
            status_text.empty()

            # Mark all researched companies as contacted so they don't re-appear next run
            for r in results:
                cid = company_id_map.get(r.company)
                if cid:
                    update_company(cid, contacted=1)

            st.success(
                f"✅ {auto_queued} auto-queued  ·  "
                f"⚠️ {partial_queued} partial (need editing)  ·  "
                f"❌ {len(failed_list)} failed"
            )
            if failed_list:
                with st.expander(f"Failed ({len(failed_list)})"):
                    for company, reason in failed_list:
                        st.caption(f"**{company}**: {reason}")
            st.rerun()

    st.subheader("Add Company Manually")
    with st.form("add_company"):
        c_name = st.text_input("Company name")
        c_website = st.text_input("Website")
        c_careers = st.text_input("Careers URL")
        c_sector = st.text_input("Sector")
        c_notes = st.text_area("Notes")
        if st.form_submit_button("Add"):
            upsert_company(c_name, c_website, c_careers, c_sector, notes=c_notes)
            st.success(f"Added {c_name}")
            st.rerun()

    # ── Funding leads ─────────────────────────────────────────────────────────
    funding_leads = get_companies(status="funding_lead")
    if funding_leads:
        st.divider()
        st.subheader(f"📰 Funding Leads ({len(funding_leads)})")
        st.caption(
            "Newly funded companies detected from Sifted / UKTN / TechCrunch. "
            "Promote interesting ones to your target list or dismiss them."
        )
        for lead in funding_leads:
            sector_tag = f"  `{lead['sector']}`" if lead.get("sector") else ""
            header = f"**{lead['name']}**{sector_tag}  —  {lead.get('notes', '')[:100]}"
            with st.expander(header):
                if lead.get("notes"):
                    st.caption(lead["notes"])
                col_p, col_d, col_w = st.columns([1, 1, 2])
                with col_p:
                    if st.button("✅ Add as target", key=f"fl_promote_{lead['id']}"):
                        update_company(lead["id"], status="target")
                        st.rerun()
                with col_d:
                    if st.button("❌ Dismiss", key=f"fl_dismiss_{lead['id']}"):
                        update_company(lead["id"], status="dismissed")
                        st.rerun()
                with col_w:
                    website = st.text_input(
                        "Add website (optional)",
                        key=f"fl_web_{lead['id']}",
                        placeholder="e.g. company.com",
                    )
                    if website and st.button("Save website", key=f"fl_save_{lead['id']}"):
                        update_company(lead["id"], website=website)
                        st.rerun()


# ── Tab 6: Stats ──────────────────────────────────────────────────────────────

with tabs[5]:
    st.header("Application Stats")
    stats = get_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Applications", stats["total_applications"])
    c2.metric("Pending", stats["pending_response"])
    c3.metric("Interviews", stats["interviews"])
    c4.metric("Offers", stats["offers"])

    apps = get_applications()
    if apps:
        df_s = pd.DataFrame(apps)
        if "status" in df_s.columns:
            st.subheader("By Status")
            st.bar_chart(df_s["status"].value_counts())

        if "applied_date" in df_s.columns:
            st.subheader("Applications Over Time")
            df_s["applied_date"] = pd.to_datetime(df_s["applied_date"])
            daily = df_s.groupby("applied_date").size().reset_index(name="count")
            st.line_chart(daily.set_index("applied_date"))

        if "company" in df_s.columns:
            st.subheader("Companies Applied To")
            st.dataframe(
                df_s[["company", "role", "applied_date", "status"]].sort_values("applied_date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.subheader("Cost Tracker")
    st.caption("Each Claude Sonnet cover letter costs ~$0.009–$0.015 USD with prompt caching active.")
    n_apps = stats["total_applications"]
    est_cost = n_apps * 0.002
    st.metric("Estimated API spend so far", f"~${est_cost:.3f} USD", help="Rough estimate at $0.002/letter average with caching")
