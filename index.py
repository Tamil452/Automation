# app.py
import streamlit as st
import pandas as pd
import os
from filelock import FileLock, Timeout
from uuid import uuid4
from datetime import datetime
from io import BytesIO

DATA_FILE = "construction_data.xlsx"
UPLOAD_DIR = "uploads"
LOCK_FILE = DATA_FILE + ".lock"
LOCK_TIMEOUT = 10  # seconds

# Ensure uploads folder exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Utility: load or create sheets ---
def ensure_workbook():
    if not os.path.exists(DATA_FILE):
        # create empty dataframes with required columns
        sheets = {
            "companies": pd.DataFrame(columns=["company_id","company_name","address","phone"]),
            "engineers": pd.DataFrame(columns=["engineer_id","name","role","phone","email","active"]),
            "sites": pd.DataFrame(columns=["site_id","site_name","location","start_date","end_date","status"]),
            "assignments": pd.DataFrame(columns=["assignment_id","engineer_id","site_id","assigned_by","assigned_on","is_active"]),
            "fund_allocations": pd.DataFrame(columns=["allocation_id","engineer_id","site_id","amount_allocated","date_allocated","balance_remaining","notes"]),
            "expenses": pd.DataFrame(columns=["expense_id","site_id","engineer_id","expense_type","amount","date","payment_mode","receipt_path","approved_by","approved","notes"]),
            "audit_log": pd.DataFrame(columns=["log_id","action","object_type","object_id","user","timestamp","details"])
        }
        with pd.ExcelWriter(DATA_FILE, engine="openpyxl") as writer:
            for name, df in sheets.items():
                df.to_excel(writer, sheet_name=name, index=False)

def read_sheet(sheet_name):
    ensure_workbook()
    try:
        return pd.read_excel(DATA_FILE, sheet_name=sheet_name, engine="openpyxl")
    except Exception:
        return pd.DataFrame()

def write_sheet(sheet_name, df):
    ensure_workbook()
    lock = FileLock(LOCK_FILE, timeout=LOCK_TIMEOUT)
    try:
        with lock:
            # read all sheets first
            with pd.ExcelWriter(DATA_FILE, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    except Timeout:
        st.error("Could not acquire lock to write data. Try again in a few seconds.")

def append_row(sheet_name, row_dict):
    df = read_sheet(sheet_name)
    df = pd.concat([df, pd.DataFrame([row_dict])], ignore_index=True)
    write_sheet(sheet_name, df)

def log(action, object_type, object_id, user, details=""):
    append_row("audit_log", {
        "log_id": str(uuid4()),
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "user": user,
        "timestamp": datetime.utcnow().isoformat(),
        "details": details
    })

# --- App UI ---
st.set_page_config(page_title="Construction Tracker", layout="wide")
st.title("Construction Company - Site & Expense Tracker")

# Simple login (MVP)
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    with st.sidebar.form("login"):
        st.write("Sign in (MVP)")
        name = st.text_input("Your name")
        email = st.text_input("Email")
        submitted = st.form_submit_button("Enter")
        if submitted:
            if name.strip() == "":
                st.warning("Please enter name")
            else:
                st.session_state.user = f"{name} <{email}>"
                st.success(f"Welcome, {name}")
                log("login", "user", "", st.session_state.user)
                st.experimental_rerun()

# load dataframes
engineers_df = read_sheet("engineers")
sites_df = read_sheet("sites")
alloc_df = read_sheet("fund_allocations")
assign_df = read_sheet("assignments")
expenses_df = read_sheet("expenses")

# Sidebar nav
page = st.sidebar.selectbox("Go to", ["Dashboard","Allocate Funds","Assign Engineer","Record Expense","Approvals","Admin","Export"])

# ------- Dashboard -------
if page == "Dashboard":
    st.header("Dashboard")
    # site summary
    st.subheader("Site Summary")
    site_summary = expenses_df.groupby("site_id", as_index=False).agg(total_spent=("amount","sum"))
    merged = sites_df.merge(site_summary, how="left", left_on="site_id", right_on="site_id")
    merged["total_spent"] = merged["total_spent"].fillna(0)
    st.dataframe(merged[["site_id","site_name","location","status","total_spent"]])

    st.subheader("Engineer Summary")
    eng_spent = expenses_df.groupby("engineer_id", as_index=False).agg(total_spent=("amount","sum"))
    eng_alloc = alloc_df.groupby("engineer_id", as_index=False).agg(total_alloc=("amount_allocated","sum"), balance=("balance_remaining","sum"))
    eng_merged = engineers_df.merge(eng_spent, left_on="engineer_id", right_on="engineer_id", how="left").merge(eng_alloc, on="engineer_id", how="left")
    eng_merged["total_spent"] = eng_merged["total_spent"].fillna(0)
    eng_merged["total_alloc"] = eng_merged["total_alloc"].fillna(0)
    eng_merged["balance"] = eng_merged["balance"].fillna(0)
    st.dataframe(eng_merged[["engineer_id","name","role","total_alloc","total_spent","balance"]])

# ------- Allocate Funds -------
elif page == "Allocate Funds":
    st.header("Allocate Funds to Engineer")
    with st.form("allocate"):
        eng_opt = engineers_df[engineers_df["active"]!=False] if not engineers_df.empty else pd.DataFrame()
        eng_choice = st.selectbox("Engineer", options=eng_opt["engineer_id"].tolist() if not eng_opt.empty else [])
        site_choice = st.selectbox("Site", options=sites_df["site_id"].tolist() if not sites_df.empty else [])
        amount = st.number_input("Amount", min_value=0.0, format="%.2f")
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Allocate")
        if submitted:
            allocation_id = str(uuid4())
            row = {
                "allocation_id": allocation_id,
                "engineer_id": eng_choice,
                "site_id": site_choice,
                "amount_allocated": float(amount),
                "date_allocated": datetime.utcnow().date().isoformat(),
                "balance_remaining": float(amount),
                "notes": notes
            }
            append_row("fund_allocations", row)
            log("allocate_funds","fund_allocations", allocation_id, st.session_state.user, details=str(row))
            st.success("Funds allocated")

# ------- Assign Engineer -------
elif page == "Assign Engineer":
    st.header("Assign Engineer to Site")
    with st.form("assign"):
        eng_choice = st.selectbox("Engineer", options=engineers_df["engineer_id"].tolist() if not engineers_df.empty else [])
        site_choice = st.selectbox("Site", options=sites_df["site_id"].tolist() if not sites_df.empty else [])
        assigned_by = st.text_input("Assigned by (manager name)", value=st.session_state.user)
        submitted = st.form_submit_button("Assign")
        if submitted:
            assignment_id = str(uuid4())
            row = {
                "assignment_id": assignment_id,
                "engineer_id": eng_choice,
                "site_id": site_choice,
                "assigned_by": assigned_by,
                "assigned_on": datetime.utcnow().date().isoformat(),
                "is_active": True
            }
            append_row("assignments", row)
            log("assign_engineer","assignments",assignment_id,st.session_state.user,str(row))
            st.success("Engineer assigned")

# ------- Record Expense -------
elif page == "Record Expense":
    st.header("Record Expense")
    with st.form("expense"):
        site_choice = st.selectbox("Site", options=sites_df["site_id"].tolist() if not sites_df.empty else [])
        eng_choice = st.selectbox("Engineer", options=engineers_df["engineer_id"].tolist() if not engineers_df.empty else [])
        exp_type = st.selectbox("Expense Type", ["Material","Labour","Transport","Misc"])
        amount = st.number_input("Amount", min_value=0.0, format="%.2f")
        date = st.date_input("Date", value=datetime.utcnow().date())
        payment_mode = st.selectbox("Payment Mode", ["Cash","Advance","Card"])
        receipt = st.file_uploader("Receipt (optional)", type=["png","jpg","jpeg","pdf"])
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Expense")
        if submitted:
            expense_id = str(uuid4())
            receipt_path = ""
            if receipt is not None:
                fname = f"{expense_id}_{receipt.name}"
                path = os.path.join(UPLOAD_DIR, fname)
                with open(path, "wb") as f:
                    f.write(receipt.getbuffer())
                receipt_path = path
            row = {
                "expense_id": expense_id,
                "site_id": site_choice,
                "engineer_id": eng_choice,
                "expense_type": exp_type,
                "amount": float(amount),
                "date": date.isoformat(),
                "payment_mode": payment_mode,
                "receipt_path": receipt_path,
                "approved_by": "",
                "approved": False,
                "notes": notes
            }
            append_row("expenses", row)
            # reduce allocation balance (simple first-fit)
            alloc_df = read_sheet("fund_allocations")
            mask = (alloc_df["engineer_id"]==eng_choice) & (alloc_df["site_id"]==site_choice) & (alloc_df["balance_remaining"]>0)
            if not alloc_df[mask].empty:
                idx = alloc_df[mask].index[0]
                alloc_df.at[idx,"balance_remaining"] = alloc_df.at[idx,"balance_remaining"] - float(amount)
                write_sheet("fund_allocations", alloc_df)
            log("create_expense","expenses",expense_id,st.session_state.user,str(row))
            st.success("Expense recorded (pending approval)")

# ------- Approvals -------
elif page == "Approvals":
    st.header("Approve Expenses")
    pending = expenses_df[expenses_df["approved"]!=True] if not expenses_df.empty else pd.DataFrame()
    if pending.empty:
        st.info("No pending expenses")
    else:
        for _, r in pending.sort_values("date", ascending=False).iterrows():
            st.write("---")
            st.write(f"Expense: {r['expense_id']} | Site: {r['site_id']} | Engineer: {r['engineer_id']} | Amount: ₹{r['amount']}")
            st.write("Notes:", r.get("notes",""))
            if r.get("receipt_path"):
                st.write("Receipt:", r["receipt_path"])
            cols = st.columns([1,1,4])
            if cols[0].button(f"Approve {r['expense_id']}", key=f"appr_{r['expense_id']}"):
                expenses_df.loc[expenses_df["expense_id"]==r["expense_id"], "approved"] = True
                expenses_df.loc[expenses_df["expense_id"]==r["expense_id"], "approved_by"] = st.session_state.user
                write_sheet("expenses", expenses_df)
                log("approve_expense","expenses",r["expense_id"],st.session_state.user,"approved")
                st.success("Approved")
                st.experimental_rerun()
            if cols[1].button(f"Reject {r['expense_id']}", key=f"rej_{r['expense_id']}"):
                expenses_df.loc[expenses_df["expense_id"]==r["expense_id"], "approved"] = False
                expenses_df.loc[expenses_df["expense_id"]==r["expense_id"], "approved_by"] = st.session_state.user
                write_sheet("expenses", expenses_df)
                log("reject_expense","expenses",r["expense_id"],st.session_state.user,"rejected")
                st.warning("Marked as reviewed (not approved)")
                st.experimental_rerun()

# ------- Admin -------
elif page == "Admin":
    st.header("Admin - Manage Engineers & Sites")
    st.subheader("Add Engineer")
    with st.form("add_eng"):
        ename = st.text_input("Name")
        ephone = st.text_input("Phone")
        eemail = st.text_input("Email")
        erole = st.selectbox("Role", ["Site Engineer","Manager"])
        submitted = st.form_submit_button("Add Engineer")
        if submitted:
            eid = st.text_input # placeholder to avoid linter
            new_id = str(uuid4())
            append_row("engineers", {"engineer_id": new_id, "name": ename, "role": erole, "phone": ephone, "email": eemail, "active": True})
            log("create_engineer","engineers", new_id, st.session_state.user,f"{ename}")
            st.success("Engineer added")

    st.subheader("Add Site")
    with st.form("add_site"):
        sname = st.text_input("Site name")
        slocation = st.text_input("Location")
        sstart = st.date_input("Start date")
        submitted = st.form_submit_button("Add Site")
        if submitted:
            sid = str(uuid4())
            append_row("sites", {"site_id": sid, "site_name": sname, "location": slocation, "start_date": sstart.isoformat(), "end_date": "", "status": "Ongoing"})
            log("create_site","sites",sid,st.session_state.user,f"{sname}")
            st.success("Site added")

# ------- Export -------
elif page == "Export":
    st.header("Export reports")
    st.write("Download sheets as CSV")
    sheets = ["companies","engineers","sites","assignments","fund_allocations","expenses","audit_log"]
    for s in sheets:
        df = read_sheet(s)
        buf = BytesIO()
        df.to_csv(buf, index=False)
        st.download_button(label=f"Download {s}.csv", data=buf.getvalue(), file_name=f"{s}.csv")

