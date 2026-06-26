# PaySync Suite - Invoice, reimbursement, and payment management platform
# Co-authored with CoCo
import streamlit as st
import os
import json
import tempfile
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST)

IST_SQL = "CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ"

st.set_page_config(
    page_title="PaySync Suite",
    page_icon=":material/sync:",
    layout="wide",
)

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()

STAGE_FQN = "INVOICE_MGMT.PUBLIC.INVOICE_FILES"
MAX_FILE_SIZE_MB = 10

FIELDS = {
    "name": "Name of Person Who raised the Invoice",
    "employee_address": "Address of The Person who raised the Invoice",
    "gst_number": "GST number of The Person who raised the Invoice",
    "bill_to_name": "Bill to name - Without including address",
    "bill_to_address": "Bill to address - Without including firm name",
    "invoice_no": "Invoice number",
    "date": "Invoice date",
    "description": "Description of services - Without Including Days Worked Statements",
    "days_worked": "Number of days worked",
    "total_days": "Total days",
    "hsn_code": "HSN/SAC code",
    "amount": "Amount",
    "total": "Total amount before tax",
    "taxable_value": "Taxable value",
    "tds_percent": "TDS percentage",
    "tds_amount": "TDS amount",
    "grand_total": "Grand total payable",
    "pan_number": "PAN number",
    "account_number": "Bank account number",
    "bank_name": "Bank name",
    "ifsc_code": "IFSC code",
    "is_signed": "Is the document signed? Answer Yes or No",
}


# ─── AUTH FUNCTIONS ───────────────────────────────────────────────────────────

def hash_password(password):
    return conn.query("SELECT SHA2(:1) AS H", params=[password]).iloc[0]["H"]


def authenticate(username, password):
    pwd_hash = hash_password(password)
    # Try ADMIN_USERS first
    result = conn.query(
        "SELECT USER_ID, USERNAME, ROLE, EMAIL, MOBILE, IS_TEMP_PASSWORD, IS_ACTIVE FROM INVOICE_MGMT.PUBLIC.ADMIN_USERS WHERE USERNAME = :1 AND PASSWORD_HASH = :2 AND IS_ACTIVE = TRUE",
        params=[username, pwd_hash],
    )
    if len(result) > 0:
        row = result.iloc[0].to_dict()
        row["AUTH_SOURCE"] = "ADMIN"
        return row
    # Try CONSULTANTS table
    result = conn.query(
        "SELECT CONSULTANT_ID, USERNAME, NAME AS FULL_NAME, EMAIL, MOBILE, IS_TEMP_PASSWORD, IS_ACTIVE FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE USERNAME = :1 AND PASSWORD_HASH = :2 AND IS_ACTIVE = TRUE",
        params=[username, pwd_hash],
    )
    if len(result) > 0:
        row = result.iloc[0].to_dict()
        row["ROLE"] = "CONSULTANT"
        row["AUTH_SOURCE"] = "CONSULTANT"
        return row
    return None


def change_password(user_data, new_password):
    new_hash = hash_password(new_password)
    if user_data.get("AUTH_SOURCE") == "CONSULTANT":
        session.sql(
            f"UPDATE INVOICE_MGMT.PUBLIC.CONSULTANTS SET PASSWORD_HASH = '{new_hash}', IS_TEMP_PASSWORD = FALSE, UPDATED_AT = {IST_SQL} WHERE CONSULTANT_ID = '{user_data['CONSULTANT_ID']}'"
        ).collect()
    else:
        session.sql(
            f"UPDATE INVOICE_MGMT.PUBLIC.ADMIN_USERS SET PASSWORD_HASH = '{new_hash}', IS_TEMP_PASSWORD = FALSE, UPDATED_AT = {IST_SQL} WHERE USER_ID = {int(user_data['USER_ID'])}"
        ).collect()


def forgot_password_verify(username, email):
    # Check ADMIN_USERS
    result = conn.query(
        "SELECT USER_ID, EMAIL, 'ADMIN' AS AUTH_SOURCE FROM INVOICE_MGMT.PUBLIC.ADMIN_USERS WHERE USERNAME = :1 AND EMAIL = :2 AND IS_ACTIVE = TRUE",
        params=[username, email],
    )
    if len(result) > 0:
        return {"USER_ID": result.iloc[0]["USER_ID"], "EMAIL": result.iloc[0]["EMAIL"], "AUTH_SOURCE": "ADMIN"}
    # Check CONSULTANTS
    result = conn.query(
        "SELECT CONSULTANT_ID, EMAIL, 'CONSULTANT' AS AUTH_SOURCE FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE USERNAME = :1 AND EMAIL = :2 AND IS_ACTIVE = TRUE",
        params=[username, email],
    )
    if len(result) > 0:
        return {"CONSULTANT_ID": result.iloc[0]["CONSULTANT_ID"], "EMAIL": result.iloc[0]["EMAIL"], "AUTH_SOURCE": "CONSULTANT"}
    return None


def send_reset_code(email, code):
    """Send a 6-digit OTP code to the user's email for password reset."""
    subject = "Invoice Management System - Password Reset Code"
    body = f"""
<html>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f7fa; margin: 0; padding: 0;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width: 500px; margin: 30px auto; background-color: #ffffff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden;">
<tr>
<td style="background: linear-gradient(135deg, #1B73E8 0%, #1557b0 100%); padding: 25px 30px; text-align: center;">
<h2 style="color: #ffffff; margin: 0; font-size: 20px;">Password Reset</h2>
</td>
</tr>
<tr>
<td style="padding: 30px;">
<p style="color: #333; font-size: 14px; line-height: 1.6;">You have requested a password reset. Use the verification code below:</p>
<div style="text-align: center; margin: 25px 0;">
<span style="display: inline-block; background: #f0f6ff; border: 2px solid #1B73E8; border-radius: 8px; padding: 15px 30px; font-size: 28px; font-weight: bold; letter-spacing: 6px; color: #1B73E8; font-family: monospace;">{code}</span>
</div>
<p style="color: #666; font-size: 13px; text-align: center;">This code is valid for <strong>10 minutes</strong>. Do not share it with anyone.</p>
<p style="color: #999; font-size: 12px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 15px;">If you did not request this, please ignore this email.</p>
</td>
</tr>
</table>
</body>
</html>
"""
    safe_body = body.replace("'", "''")
    try:
        session.sql(f"""
            CALL SYSTEM$SEND_EMAIL(
                'invoice_notifications',
                '{email}',
                '{subject}',
                '{safe_body}',
                'text/html'
            )
        """).collect()
        return True
    except Exception:
        return False


def reset_password(reset_info, new_password):
    new_hash = hash_password(new_password)
    if reset_info["AUTH_SOURCE"] == "CONSULTANT":
        session.sql(
            f"UPDATE INVOICE_MGMT.PUBLIC.CONSULTANTS SET PASSWORD_HASH = '{new_hash}', IS_TEMP_PASSWORD = FALSE, UPDATED_AT = {IST_SQL} WHERE CONSULTANT_ID = '{reset_info['CONSULTANT_ID']}'"
        ).collect()
    else:
        session.sql(
            f"UPDATE INVOICE_MGMT.PUBLIC.ADMIN_USERS SET PASSWORD_HASH = '{new_hash}', IS_TEMP_PASSWORD = FALSE, UPDATED_AT = {IST_SQL} WHERE USER_ID = {int(reset_info['USER_ID'])}"
        ).collect()


def log_history(table_name, record_id, field_updated, old_value, new_value, updated_by):
    safe_old = str(old_value).replace("'", "''") if old_value is not None else ""
    safe_new = str(new_value).replace("'", "''") if new_value is not None else ""
    session.sql(f"""
        INSERT INTO INVOICE_MGMT.PUBLIC.APP_USERS_HISTORY
        (TABLE_NAME, RECORD_ID, FIELD_UPDATED, OLD_VALUE, NEW_VALUE, UPDATED_BY)
        VALUES ('{table_name}', '{record_id}', '{field_updated}', '{safe_old}', '{safe_new}', '{updated_by}')
    """).collect()


APP_URL = "www.google.com"

def send_welcome_email(consultant_email, consultant_name, username, temp_password):
    safe_name = consultant_name.replace("'", "''")
    subject = "Welcome to PaySync Suite - Your Login Credentials"
    body = f"""
<html>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f7fa; margin: 0; padding: 0;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 30px auto; background-color: #ffffff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden;">
<tr>
<td style="background: linear-gradient(135deg, #1B73E8 0%, #1557b0 100%); padding: 30px 40px; text-align: center;">
<h1 style="color: #ffffff; margin: 0; font-size: 22px;">PaySync Suite</h1>
<p style="color: #b3d4fc; margin: 8px 0 0 0; font-size: 14px;">Welcome Aboard!</p>
</td>
</tr>
<tr>
<td style="padding: 35px 40px;">
<p style="color: #333333; font-size: 16px; margin: 0 0 20px 0;">Dear <strong>{safe_name}</strong>,</p>
<p style="color: #555555; font-size: 14px; line-height: 1.6; margin: 0 0 20px 0;">
Your account has been created on PaySync Suite. Please find your login credentials below:
</p>
<table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f0f6ff; border-radius: 8px; padding: 20px; margin: 20px 0;">
<tr>
<td style="padding: 15px 25px;">
<p style="margin: 0 0 10px 0; color: #64748B; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;">Username</p>
<p style="margin: 0 0 18px 0; color: #1B73E8; font-size: 18px; font-weight: bold;">{username}</p>
<p style="margin: 0 0 10px 0; color: #64748B; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;">Temporary Password</p>
<p style="margin: 0; color: #1B73E8; font-size: 18px; font-weight: bold; font-family: monospace;">{temp_password}</p>
</td>
</tr>
</table>
<div style="background-color: #FFF8E1; border-left: 4px solid #FFA000; padding: 12px 16px; border-radius: 4px; margin: 20px 0;">
<p style="color: #E65100; font-size: 13px; margin: 0; font-weight: 600;">Important: You must change your password upon first login.</p>
</div>
<p style="color: #555555; font-size: 14px; line-height: 1.6; margin: 20px 0;">
Access the portal using the link below:
</p>
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td align="center" style="padding: 10px 0 25px 0;">
<a href="{APP_URL}" style="background-color: #1B73E8; color: #ffffff; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-size: 14px; font-weight: 600; display: inline-block;">Login to Portal</a>
</td>
</tr>
</table>
<p style="color: #999999; font-size: 12px; margin: 20px 0 0 0; border-top: 1px solid #eee; padding-top: 15px;">
If you did not expect this email, please contact the administration team immediately.
</p>
</td>
</tr>
<tr>
<td style="background-color: #f8fafc; padding: 18px 40px; text-align: center; border-top: 1px solid #e2e8f0;">
<p style="color: #94a3b8; font-size: 11px; margin: 0;">PaySync Suite | This is an automated message</p>
</td>
</tr>
</table>
</body>
</html>
"""
    safe_body = body.replace("'", "''")
    try:
        session.sql(f"""
            CALL SYSTEM$SEND_EMAIL(
                'invoice_notifications',
                '{consultant_email}',
                '{subject}',
                '{safe_body}',
                'text/html'
            )
        """).collect()
        return True
    except Exception:
        return False


# ─── LOGIN PAGE ───────────────────────────────────────────────────────────────

def show_login():
    import base64

    _SVG = '<svg width="60" height="60" viewBox="0 0 60 60" fill="none" xmlns="http://www.w3.org/2000/svg"><rect width="60" height="60" rx="12" fill="url(#grad)"/><defs><linearGradient id="grad" x1="0" y1="0" x2="60" y2="60" gradientUnits="userSpaceOnUse"><stop stop-color="#667eea"/><stop offset="1" stop-color="#764ba2"/></linearGradient></defs><text x="7" y="41" font-family="Arial" font-size="26" fill="white" font-weight="bold">PS</text></svg>'
    logo_b64 = base64.b64encode(_SVG.encode('utf-8')).decode('utf-8')

    st.markdown(f"""
    <style>
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden !important;}}
    section[data-testid="stSidebar"] {{ display: none !important; }}
    .block-container {{ padding-top: 0 !important; padding-bottom: 0 !important; max-width: 100% !important; }}
    .brand-panel {{
        background: linear-gradient(135deg, #0a0f1e 0%, #13203d 40%, #1f3d6d 100%);
        padding: 3rem 2rem;
        border-radius: 12px;
        min-height: 520px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
    }}
    .brand-panel img {{ margin-bottom: 1.5rem; }}
    .brand-panel h1 {{
        color: #FFFFFF;
        font-size: 2rem;
        font-weight: 700;
        margin: 0 0 0.5rem 0;
        letter-spacing: 0.5px;
    }}
    .brand-panel p {{
        color: #b0c4de;
        font-size: 0.95rem;
        margin: 0 0 2rem 0;
        line-height: 1.5;
        max-width: 320px;
    }}
    .brand-features {{
        text-align: left;
        padding: 0;
        margin: 0;
        list-style: none;
    }}
    .brand-features li {{
        color: #cbd5e1;
        font-size: 0.85rem;
        padding: 6px 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .brand-features li::before {{
        content: "✓";
        color: #667eea;
        font-weight: 700;
        font-size: 1rem;
    }}
    .login-form-header {{
        margin-bottom: 1.5rem;
        padding-top: 1rem;
    }}
    .login-form-header h2 {{
        font-size: 1.4rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0 0 0.3rem 0;
    }}
    .login-form-header p {{
        font-size: 0.85rem;
        color: #64748b;
        margin: 0;
    }}
    .stButton button, .stForm button {{
        border-radius: 8px;
        font-weight: 600;
        background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important;
        color: white !important;
        border: none !important;
        transition: all 0.3s ease;
    }}
    .stButton button:hover, .stForm button:hover {{
        background: linear-gradient(90deg, #1a3359, #1f3d6d, #2c4e8a) !important;
        transform: translateY(-2px);
    }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 2px; background-color: transparent; padding: 0; border-bottom: 2px solid #1f3d6d; }}
    .stTabs [data-baseweb="tab"] {{ padding: 10px 20px; background-color: #e6ecf5; color: #0a0f1e; border: none; font-weight: 500; transition: all 0.3s; margin-right: 2px; }}
    .stTabs [data-baseweb="tab"]:hover {{ background-color: #cbd6e6; }}
    .stTabs [aria-selected="true"] {{ background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; color: white !important; font-weight: 600; }}
    .stTextInput > div > div > input {{ border-radius: 8px; border: 1px solid #cbd6e6; background-color: white; transition: all 0.3s; }}
    .stTextInput > div > div > input:focus {{ border-color: #2c4e8a; box-shadow: 0 0 0 2px rgba(44,78,138,0.15); }}
    .stAlert {{ border-radius: 10px; border-left: 5px solid #1f3d6d; background: white; }}
    .login-footer {{
        text-align: center;
        padding: 1rem 0 0 0;
        margin-top: 1.5rem;
        border-top: 1px solid #e2e8f0;
        font-size: 0.7rem;
        color: #94a3b8;
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }}
    </style>
    """, unsafe_allow_html=True)

    col_brand, col_spacer, col_form = st.columns([5, 1, 5])

    with col_brand:
        st.markdown(f"""
        <div class="brand-panel">
            <img src="data:image/svg+xml;base64,{logo_b64}" width="60" height="60" alt="Logo"/>
            <h1>PaySync Suite</h1>
            <p>Your unified platform for professional service invoicing, reimbursement claims, and real-time payment tracking — all in one place.</p>
            <ul class="brand-features">
                <li>Professional service invoices with AI extraction</li>
                <li>Reimbursement claims & expense submissions</li>
                <li>Real-time invoice status tracking</li>
                <li>Automated payment processing workflows</li>
                <li>Role-based portals for consultants & admin</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    with col_form:
        st.markdown("""
        <div class="login-form-header">
            <h2>Sign in to your account</h2>
            <p>Enter your credentials to access the portal</p>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_forgot = st.tabs([":material/login: Sign In", ":material/lock_reset: Forgot Password"])

        with tab_login:
            with st.form("login_form"):
                username = st.text_input("Username", placeholder="Enter your username")
                password = st.text_input("Password", type="password", placeholder="Enter your password")
                st.markdown("")
                submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")
                if submitted:
                    if username and password:
                        user = authenticate(username, password)
                        if user:
                            st.session_state["authenticated"] = True
                            st.session_state["user"] = user
                            st.session_state["user_role"] = user["ROLE"]
                            if user["IS_TEMP_PASSWORD"]:
                                st.session_state["must_change_password"] = True
                            st.rerun()
                        else:
                            st.error("Invalid username or password.")
                    else:
                        st.warning("Please enter both fields.")

        with tab_forgot:
            import random as _random

            # Step 1: Verify username + email, send OTP
            if not st.session_state.get("reset_code_sent"):
                with st.form("forgot_form"):
                    fg_user = st.text_input("Username")
                    fg_email = st.text_input("Registered Email")
                    fg_sub = st.form_submit_button("Send Verification Code", use_container_width=True)
                    if fg_sub and fg_user and fg_email:
                        reset_info = forgot_password_verify(fg_user, fg_email)
                        if reset_info:
                            code = str(_random.randint(100000, 999999))
                            email_sent = send_reset_code(reset_info["EMAIL"], code)
                            if email_sent:
                                st.session_state["reset_info"] = reset_info
                                st.session_state["reset_code"] = code
                                st.session_state["reset_code_sent"] = True
                                st.session_state["reset_code_time"] = now_ist()
                                st.rerun()
                            else:
                                st.error("Failed to send verification email. Please try again.")
                        else:
                            st.error("Username and email do not match.")

            # Step 2: Enter OTP code
            elif not st.session_state.get("reset_code_verified"):
                masked_email = st.session_state["reset_info"]["EMAIL"]
                parts = masked_email.split("@")
                if len(parts[0]) > 3:
                    masked_email = parts[0][:3] + "***@" + parts[1]
                else:
                    masked_email = parts[0][0] + "***@" + parts[1]

                st.info(f"A 6-digit verification code has been sent to **{masked_email}**. Please check your inbox.")

                with st.form("otp_form"):
                    otp_input = st.text_input("Enter 6-Digit Code", max_chars=6, placeholder="e.g. 123456")
                    otp_sub = st.form_submit_button("Verify Code", use_container_width=True, type="primary")
                    if otp_sub:
                        if not otp_input or len(otp_input) != 6:
                            st.error("Please enter a valid 6-digit code.")
                        else:
                            # Check expiry (10 minutes)
                            code_time = st.session_state.get("reset_code_time")
                            if code_time and (now_ist() - code_time) > timedelta(minutes=10):
                                st.error("Code expired. Please start over.")
                                st.session_state.pop("reset_code_sent", None)
                                st.session_state.pop("reset_code", None)
                                st.session_state.pop("reset_code_time", None)
                            elif otp_input == st.session_state.get("reset_code"):
                                st.session_state["reset_code_verified"] = True
                                st.rerun()
                            else:
                                st.error("Invalid code. Please try again.")

                if st.button("Resend Code", use_container_width=True):
                    code = str(_random.randint(100000, 999999))
                    send_reset_code(st.session_state["reset_info"]["EMAIL"], code)
                    st.session_state["reset_code"] = code
                    st.session_state["reset_code_time"] = now_ist()
                    st.success("A new code has been sent to your email.")

                if st.button("Start Over", use_container_width=True):
                    for k in ["reset_code_sent", "reset_code", "reset_code_time", "reset_info", "reset_code_verified"]:
                        st.session_state.pop(k, None)
                    st.rerun()

            # Step 3: Set new password
            else:
                st.success("Code verified! Set your new password below.")
                with st.form("reset_form"):
                    new_pwd = st.text_input("New Password", type="password")
                    confirm_pwd = st.text_input("Confirm Password", type="password")
                    if st.form_submit_button("Change Password", type="primary", use_container_width=True):
                        if new_pwd == confirm_pwd and len(new_pwd) >= 8:
                            reset_password(st.session_state["reset_info"], new_pwd)
                            st.success("Password changed successfully! Please login with your new password.")
                            for k in ["reset_code_sent", "reset_code", "reset_code_time", "reset_info", "reset_code_verified"]:
                                st.session_state.pop(k, None)
                        else:
                            st.error("Passwords must match and be at least 8 characters.")

        st.markdown('<div class="login-footer">PAYSYNC SUITE</div>', unsafe_allow_html=True)


def show_change_password():
    st.title(":material/lock_reset: Change Your Password")
    st.info("You have a temporary password. Please set a new one.")
    with st.form("change_pwd"):
        new_pwd = st.text_input("New Password", type="password")
        confirm_pwd = st.text_input("Confirm Password", type="password")
        if st.form_submit_button("Update Password", type="primary", use_container_width=True):
            if new_pwd == confirm_pwd and len(new_pwd) >= 8:
                change_password(st.session_state["user"], new_pwd)
                st.session_state["must_change_password"] = False
                st.session_state["user"]["IS_TEMP_PASSWORD"] = False
                st.rerun()
            else:
                st.error("Passwords must match and be 8+ characters.")


# ─── AI EXTRACTION ────────────────────────────────────────────────────────────

def extract_invoice_data(staged_file_name):
    """Try AI_EXTRACT, fallback to CORTEX.COMPLETE, fallback to empty."""
    response_format_sql = "{" + ", ".join(f"'{k}': '{v}'" for k, v in FIELDS.items()) + "}"

    # Attempt 1: AI_EXTRACT
    try:
        result = session.sql(f"""
            SELECT AI_EXTRACT(
                file => TO_FILE('@{STAGE_FQN}', '{staged_file_name}'),
                responseFormat => {response_format_sql}
            ) AS EXTRACTED_FIELDS
        """).collect()
        if result:
            raw = json.loads(result[0]["EXTRACTED_FIELDS"])
            return json.dumps(raw.get("response", raw))
    except Exception:
        pass

    # Attempt 2: CORTEX.COMPLETE with file
    try:
        fields_list = "\\n".join([f'- {k}: {v}' for k, v in FIELDS.items()])
        prompt = f"Extract these fields from the invoice PDF. Return ONLY valid JSON with these exact keys (use null if not found):\\n{fields_list}"
        safe_prompt = prompt.replace("'", "''")

        result = session.sql(f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                'claude-3-5-sonnet',
                ARRAY_CONSTRUCT(
                    OBJECT_CONSTRUCT(
                        'role', 'user',
                        'content', ARRAY_CONSTRUCT(
                            OBJECT_CONSTRUCT('type', 'text', 'text', '{safe_prompt}'),
                            OBJECT_CONSTRUCT('type', 'file', 'file', TO_FILE('@{STAGE_FQN}', '{staged_file_name}'))
                        )
                    )
                ),
                OBJECT_CONSTRUCT('temperature', 0, 'max_tokens', 4096)
            ) AS RESULT
        """).collect()

        if result:
            raw_resp = json.loads(result[0]["RESULT"])
            choices = raw_resp.get("choices", [])
            if choices:
                text = choices[0].get("messages", choices[0].get("message", {}).get("content", ""))
                if isinstance(text, list):
                    text = text[0].get("content", "") if text else ""
            else:
                text = raw_resp.get("messages", str(raw_resp))
                if isinstance(text, list):
                    text = text[0].get("content", "") if text else str(text)

            # Extract JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                candidate = text[start:end]
                json.loads(candidate)  # validate
                return candidate
    except Exception:
        pass

    # Attempt 3: Return empty extraction
    return json.dumps({k: None for k in FIELDS.keys()})


# ─── CONSULTANT PORTAL ────────────────────────────────────────────────────────

def consultant_portal():
    user = st.session_state["user"]
    consultant_id = user["CONSULTANT_ID"]

    # Hide sidebar, use top nav instead
    st.markdown("""
    <style>
        section[data-testid="stSidebar"] { display: none !important; }
        .block-container { background-color: #f0f4f8; }
        .portal-header { width: 100%; background: linear-gradient(90deg, #0a0f1e, #13203d, #1f3d6d); padding: 20px 30px; display: flex; align-items: center; gap: 16px; box-shadow: 0 4px 20px rgba(10,15,30,0.4); border-bottom: 3px solid #2c4e8a; margin-bottom: 25px; border-radius: 8px; }
        .portal-header h2 { font-size: 24px; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 0.5px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        .portal-header p { font-size: 13px; color: #b0c4de; margin: 4px 0 0 0; font-weight: 300; letter-spacing: 0.3px; }
        .stButton button { border-radius: 8px; font-weight: 600; background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; border: none !important; transition: all 0.3s ease; }
        .stButton button:hover { background: linear-gradient(90deg, #1a3359, #1f3d6d, #2c4e8a) !important; transform: translateY(-2px); }
        .stForm button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; border: none !important; border-radius: 8px; font-weight: 600; padding: 10px 20px; }
        .stTabs [data-baseweb="tab-list"] { gap: 2px; background-color: transparent; padding: 0; border-bottom: 2px solid #1f3d6d; }
        .stTabs [data-baseweb="tab"] { padding: 10px 20px; background-color: #e6ecf5; color: #0a0f1e; border: none; font-weight: 500; transition: all 0.3s; margin-right: 2px; }
        .stTabs [data-baseweb="tab"]:hover { background-color: #cbd6e6; }
        .stTabs [aria-selected="true"] { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; color: white !important; font-weight: 600; }
        .stTextInput > div > div > input, .stSelectbox > div > div > div { border-radius: 8px; border: 1px solid #cbd6e6; background-color: white; transition: all 0.3s; }
        .stAlert { border-radius: 10px; border-left: 5px solid #1f3d6d; background: white; }
        .stDownloadButton button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; }
        .stProgress > div > div { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; }
        hr { border-color: #1f3d6d !important; opacity: 0.2; }
    </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown(
        f"""<div class="portal-header">
            <div style="flex:1;">
                <h2>Consultant Invoice Portal</h2>
                <p>{user['FULL_NAME']} &nbsp;|&nbsp; {consultant_id}</p>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Top action buttons (right-aligned)
    nav_spacer, nav_pwd, nav_logout = st.columns([6, 2, 1.5])
    with nav_pwd:
        if st.button(":material/lock_reset: Change Password", use_container_width=True, key="consultant_chg_pwd"):
            st.session_state["show_consultant_pwd_change"] = not st.session_state.get("show_consultant_pwd_change", False)
    with nav_logout:
        if st.button(":material/logout: Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # Collapsible change password section
    if st.session_state.get("show_consultant_pwd_change"):
        with st.expander(":material/lock_reset: Change Password", expanded=True):
            with st.form("consultant_change_pwd_form"):
                cp1, cp2, cp3 = st.columns(3)
                with cp1:
                    cur_pwd = st.text_input("Current Password", type="password", key="cons_cur_pwd")
                with cp2:
                    new_pwd = st.text_input("New Password", type="password", key="cons_new_pwd")
                with cp3:
                    confirm_pwd = st.text_input("Confirm New Password", type="password", key="cons_confirm_pwd")
                if st.form_submit_button("Update Password", type="primary", use_container_width=True):
                    if not cur_pwd or not new_pwd or not confirm_pwd:
                        st.error("All fields are required.")
                    elif new_pwd != confirm_pwd:
                        st.error("New passwords do not match.")
                    elif len(new_pwd) < 8:
                        st.error("Password must be at least 8 characters.")
                    else:
                        cur_hash = hash_password(cur_pwd)
                        verify = conn.query(
                            "SELECT CONSULTANT_ID FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE CONSULTANT_ID = :1 AND PASSWORD_HASH = :2",
                            params=[consultant_id, cur_hash],
                        )
                        if len(verify) == 0:
                            st.error("Current password is incorrect.")
                        else:
                            new_hash = hash_password(new_pwd)
                            session.sql(
                                f"UPDATE INVOICE_MGMT.PUBLIC.CONSULTANTS SET PASSWORD_HASH = '{new_hash}', UPDATED_AT = {IST_SQL} WHERE CONSULTANT_ID = '{consultant_id}'"
                            ).collect()
                            st.success("Password changed successfully!")
                            st.session_state.pop("show_consultant_pwd_change", None)

    # Success confirmation (shown at bottom after rerun)
    tab_submit, tab_status = st.tabs([":material/description: Raise an Invoice", ":material/search: Invoice Status"])

    # ─── RAISE AN INVOICE TAB ─────────────────────────────────────────────────
    with tab_submit:
        st.markdown("#### Raise an Invoice")

        # Step 1: Invoice type first
        invoice_type = st.selectbox("Invoice Type", ["Professional Service", "Reimbursement", "Others"], key="inv_type_select")

        # Step 2: Month (for Professional Service) or Date (for others)
        if invoice_type == "Professional Service":
            # Generate months from June 2026 onwards
            start_year, start_month = 2026, 6
            month_options = []
            month_values = []
            now = now_ist()
            y, m = start_year, start_month
            while (y < now.year) or (y == now.year and m <= now.month):
                month_values.append(f"{y}-{m:02d}")
                month_options.append(datetime(y, m, 1).strftime("%B %Y"))
                m += 1
                if m > 12:
                    m = 1
                    y += 1
            month_values.reverse()
            month_options.reverse()

            selected_idx = st.selectbox("Invoice Month", range(len(month_options)), format_func=lambda x: month_options[x])
            invoice_month = month_values[selected_idx]

            # Duplicate check only for Professional Service (one per month)
            existing = session.sql(
                f"SELECT INVOICE_ID, STATUS FROM INVOICE_MGMT.PUBLIC.INVOICES WHERE CONSULTANT_ID = '{consultant_id}' AND INVOICE_MONTH = '{invoice_month}' AND INVOICE_TYPE = '{invoice_type}'"
            ).collect()

            can_upload = True
            existing_status = None
            if len(existing) > 0:
                existing_status = existing[0]["STATUS"]
                if existing_status in ("REJECTED",):
                    st.info("Previous invoice was rejected. You may re-submit.")
                elif existing_status == "PAYMENT PROCESSED":
                    can_upload = False
                    st.warning(f"Your **{invoice_type}** invoice for this period has been **processed and paid**.")
                else:
                    can_upload = False
                    st.warning(f"Your **{invoice_type}** invoice for this period is already submitted. Current status: **{existing_status}**.")
        else:
            invoice_date = now_ist().date()
            st.text_input("Invoice Date", value=invoice_date.strftime("%d %b %Y"), disabled=True)
            invoice_month = invoice_date.strftime("%Y-%m")
            can_upload = True  # No restriction for reimbursement/others

        # Step 3: Amount (for Reimbursement/Others)
        total_amount = None
        if invoice_type != "Professional Service":
            label = "Reimbursement Amount" if invoice_type == "Reimbursement" else "Amount"
            total_amount = st.number_input(label, min_value=0.0, step=100.0, format="%.2f")

        # Step 4: File upload
        if invoice_type == "Professional Service":
            uploaded_file = st.file_uploader(
                f"Upload Invoice (PDF or Image, max {MAX_FILE_SIZE_MB}MB)",
                type=["pdf", "png", "jpg", "jpeg", "tiff", "bmp"],
                disabled=not can_upload,
            )
        else:
            uploaded_file = st.file_uploader(
                f"Upload Supporting Document (any file, max {MAX_FILE_SIZE_MB}MB)",
                disabled=not can_upload,
            )

        file_too_large = False
        if uploaded_file:
            size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                st.error(f"File is {size_mb:.1f}MB — exceeds {MAX_FILE_SIZE_MB}MB limit.")
                file_too_large = True

        remarks = st.text_input("Remarks (optional)", placeholder="Any notes about this invoice...")

        st.markdown("")
        if st.button(":material/send: Submit Invoice", type="primary", use_container_width=True, disabled=(not can_upload or file_too_large)):
            if not can_upload:
                st.error(f"Invoice already submitted for this month & type (Status: **{existing_status}**). Re-upload only allowed if rejected.")
            elif uploaded_file is None:
                st.error("Please upload a supporting document / invoice file. Attachment is mandatory.")
            elif invoice_type != "Professional Service" and (total_amount is None or total_amount <= 0):
                st.error("Please enter a valid amount greater than 0.")
            else:
                with st.spinner("Uploading and processing..."):
                    orig_name = uploaded_file.name.replace(" ", "_")
                    staged_name = f"{consultant_id}_{invoice_month}_{invoice_type.replace(' ', '_')}_{now_ist().strftime('%Y%m%d%H%M%S')}_{orig_name}"
                    tmp_dir = tempfile.mkdtemp()
                    tmp_path = os.path.join(tmp_dir, staged_name)
                    with open(tmp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    session.file.put(tmp_path, f"@{STAGE_FQN}", auto_compress=False, overwrite=True)
                    os.unlink(tmp_path)

                    if invoice_type == "Professional Service" and len(existing) > 0 and can_upload:
                        session.sql(f"DELETE FROM INVOICE_MGMT.PUBLIC.INVOICES WHERE CONSULTANT_ID = '{consultant_id}' AND INVOICE_MONTH = '{invoice_month}' AND INVOICE_TYPE = '{invoice_type}'").collect()

                    # AI extraction only for Professional Service
                    if invoice_type == "Professional Service":
                        extracted_json = extract_invoice_data(staged_name)
                    else:
                        extracted_json = json.dumps({})

                    safe_remarks = remarks.replace("'", "''") if remarks else ""
                    amount_sql = f"{total_amount}" if total_amount else "NULL"

                    # Generate type-specific invoice reference
                    prefix_map = {"Professional Service": "PS", "Reimbursement": "RE", "Others": "OT"}
                    prefix = prefix_map.get(invoice_type, "INV")
                    max_ref = conn.query(
                        f"SELECT MAX(TRY_TO_NUMBER(REPLACE(INVOICE_REF, '{prefix}-', ''))) AS MAX_NUM FROM INVOICE_MGMT.PUBLIC.INVOICES WHERE INVOICE_REF LIKE '{prefix}-%'"
                    ).iloc[0]["MAX_NUM"]
                    next_num = int(max_ref) + 1 if max_ref and max_ref == max_ref else 1
                    invoice_ref = f"{prefix}-{next_num:04d}"

                    session.sql(f"""
                        INSERT INTO INVOICE_MGMT.PUBLIC.INVOICES
                        (CONSULTANT_ID, INVOICE_TYPE, INVOICE_MONTH, FILE_NAME, STAGE_PATH, AI_EXTRACTED_DATA, STATUS, REMARKS, TOTAL_AMOUNT, INVOICE_REF)
                        SELECT '{consultant_id}', '{invoice_type}', '{invoice_month}', '{staged_name}',
                            '@{STAGE_FQN}/{staged_name}', PARSE_JSON($${extracted_json}$$), 'UNDER PROCESS', '{safe_remarks}', {amount_sql}, '{invoice_ref}'
                    """).collect()

                st.session_state["invoice_submitted"] = True
                st.session_state["submitted_type"] = invoice_type
                st.rerun()

        # Show success message at bottom after submission
        if st.session_state.get("invoice_submitted"):
            submitted_type = st.session_state.get("submitted_type", "Professional Service")
            if submitted_type == "Professional Service":
                st.success("Your invoice has been submitted successfully! It will be reviewed and processed as per company policy.")
            else:
                st.success(f"Your **{submitted_type}** claim has been submitted successfully! It will be reviewed by the accounting team.")
            st.session_state.pop("invoice_submitted", None)
            st.session_state.pop("submitted_type", None)

    # ─── INVOICE STATUS TAB ───────────────────────────────────────────────────
    with tab_status:
        st.markdown("#### Invoice Status")

        # Generate month options for filter
        start_year, start_month = 2026, 6
        month_options_status = []
        month_values_status = []
        now = now_ist()
        y, m = start_year, start_month
        while (y < now.year) or (y == now.year and m <= now.month):
            month_values_status.append(f"{y}-{m:02d}")
            month_options_status.append(datetime(y, m, 1).strftime("%B %Y"))
            m += 1
            if m > 12:
                m = 1
                y += 1
        month_values_status.reverse()
        month_options_status.reverse()

        # Filters
        f1, f2 = st.columns(2)
        with f1:
            view_mode = st.radio("View", ["Last 5 Invoices", "Select Month(s)"], horizontal=True, label_visibility="collapsed")
        with f2:
            type_filter = st.selectbox("Filter by Type", ["All", "Professional Service", "Reimbursement", "Others"], key="status_type_filter")

        type_where = f"AND INVOICE_TYPE = '{type_filter}'" if type_filter != "All" else ""

        if view_mode == "Last 5 Invoices":
            invoices = session.sql(f"""
                SELECT INVOICE_ID, INVOICE_REF, INVOICE_MONTH, INVOICE_TYPE, FILE_NAME, STATUS, UPLOADED_AT, REJECTION_REASON, REMARKS, TOTAL_AMOUNT,
                       AI_EXTRACTED_DATA:"name"::STRING AS EXTRACTED_NAME,
                       AI_EXTRACTED_DATA:"invoice_no"::STRING AS INVOICE_NUMBER,
                       AI_EXTRACTED_DATA:"date"::STRING AS INVOICE_DATE,
                       AI_EXTRACTED_DATA:"gst_number"::STRING AS GST_NUMBER,
                       AI_EXTRACTED_DATA:"grand_total"::STRING AS GRAND_TOTAL
                FROM INVOICE_MGMT.PUBLIC.INVOICES
                WHERE CONSULTANT_ID = '{consultant_id}' {type_where}
                ORDER BY UPLOADED_AT DESC
                LIMIT 5
            """).to_pandas()
        else:
            selected_months = st.multiselect("Select Month(s)", month_options_status)
            selected_raw = [month_values_status[month_options_status.index(m)] for m in selected_months if m in month_options_status]

            if selected_raw:
                in_clause = ",".join([f"'{v}'" for v in selected_raw])
                invoices = session.sql(f"""
                SELECT INVOICE_ID, INVOICE_REF, INVOICE_MONTH, INVOICE_TYPE, FILE_NAME, STATUS, UPLOADED_AT, REJECTION_REASON, REMARKS, TOTAL_AMOUNT,
                           AI_EXTRACTED_DATA:"name"::STRING AS EXTRACTED_NAME,
                           AI_EXTRACTED_DATA:"invoice_no"::STRING AS INVOICE_NUMBER,
                           AI_EXTRACTED_DATA:"date"::STRING AS INVOICE_DATE,
                           AI_EXTRACTED_DATA:"gst_number"::STRING AS GST_NUMBER,
                           AI_EXTRACTED_DATA:"grand_total"::STRING AS GRAND_TOTAL
                    FROM INVOICE_MGMT.PUBLIC.INVOICES
                    WHERE CONSULTANT_ID = '{consultant_id}' AND INVOICE_MONTH IN ({in_clause}) {type_where}
                    ORDER BY UPLOADED_AT DESC
                """).to_pandas()
            else:
                invoices = session.sql("SELECT 1 WHERE FALSE").to_pandas()

        if len(invoices) == 0:
            st.info("No invoices found.")
        else:
            for _, inv in invoices.iterrows():
                try:
                    display_month = datetime.strptime(inv['INVOICE_MONTH'], "%Y-%m").strftime("%B %Y")
                except (ValueError, TypeError):
                    display_month = inv['INVOICE_MONTH']

                badge_colors = {
                    "UNDER PROCESS": ("#FFF3E0", "#E65100", "🟠"),
                    "DETAILS VERIFIED": ("#E3F2FD", "#1565C0", "🔵"),
                    "PAYMENT IN PROCESS": ("#F3E5F5", "#6A1B9A", "🟣"),
                    "PAYMENT PROCESSED": ("#E8F5E9", "#2E7D32", "🟢"),
                    "REJECTED": ("#FFEBEE", "#C62828", "🔴"),
                }
                bg, fg, dot = badge_colors.get(inv["STATUS"], ("#F5F5F5", "#333", "⚪"))

                with st.container(border=True):
                    # Header row with status
                    h1, h2, h3 = st.columns([3, 3, 1])
                    with h1:
                        ref_display = f"`{inv['INVOICE_REF']}` " if inv.get("INVOICE_REF") else ""
                        if inv["INVOICE_TYPE"] == "Professional Service":
                            st.markdown(f"{ref_display}**{display_month}** — {inv['INVOICE_TYPE']}")
                        else:
                            uploaded_at = inv.get("UPLOADED_AT")
                            try:
                                date_str = uploaded_at.strftime('%d %b %Y') if uploaded_at and uploaded_at == uploaded_at else display_month
                            except Exception:
                                date_str = display_month
                            st.markdown(f"{ref_display}**{date_str}** — {inv['INVOICE_TYPE']}")
                    with h2:
                        st.markdown(
                            f'<span style="background:{bg}; color:{fg}; padding:4px 14px; border-radius:16px; font-size:0.8rem; font-weight:600;">{dot} {inv["STATUS"]}</span>',
                            unsafe_allow_html=True,
                        )
                    with h3:
                        try:
                            dl_dir = tempfile.mkdtemp()
                            session.file.get(f"@{STAGE_FQN}/{inv['FILE_NAME']}", dl_dir)
                            dl_path = os.path.join(dl_dir, inv["FILE_NAME"])
                            if os.path.exists(dl_path):
                                with open(dl_path, "rb") as f:
                                    st.download_button(
                                        ":material/download:",
                                        data=f.read(),
                                        file_name=inv["FILE_NAME"],
                                        mime="application/octet-stream",
                                        key=f"dl_{inv['INVOICE_ID']}",
                                        use_container_width=True,
                                    )
                                os.unlink(dl_path)
                        except Exception:
                            st.caption("—")

                    # Remarks prominently at top if present
                    if inv.get("REMARKS") and str(inv["REMARKS"]).strip():
                        st.markdown(
                            f'<div style="background:#F5F5F5; padding:8px 14px; border-radius:8px; margin:4px 0 10px 0; font-size:0.9rem;">'
                            f'<strong>Remarks:</strong> {inv["REMARKS"]}</div>',
                            unsafe_allow_html=True,
                        )

                    if inv["REJECTION_REASON"]:
                        st.error(f"Reason: {inv['REJECTION_REASON']}")

                    # Details depend on invoice type
                    if inv["INVOICE_TYPE"] == "Professional Service":
                        has_gst = inv["GST_NUMBER"] and str(inv["GST_NUMBER"]).strip() and str(inv["GST_NUMBER"]).strip().lower() not in ("null", "none", "")
                        if has_gst:
                            c1, c2, c3, c4, c5 = st.columns(5)
                        else:
                            c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.caption("NAME")
                            st.markdown(f"**{inv['EXTRACTED_NAME'] or user['FULL_NAME']}**")
                        with c2:
                            st.caption("INVOICE #")
                            st.markdown(f"**{inv['INVOICE_NUMBER'] or '—'}**")
                        with c3:
                            st.caption("DATE")
                            st.markdown(f"**{inv['INVOICE_DATE'] or '—'}**")
                        with c4:
                            st.caption("AMOUNT")
                            st.markdown(f"**{inv['GRAND_TOTAL'] or '—'}**")
                        if has_gst:
                            with c5:
                                st.caption("GST")
                                st.markdown(f"**{inv['GST_NUMBER']}**")
                    else:
                        # Reimbursement / Others - show date raised and amount
                        c1, c2 = st.columns(2)
                        with c1:
                            st.caption("DATE RAISED")
                            uploaded_at = inv.get("UPLOADED_AT")
                            if uploaded_at and uploaded_at == uploaded_at:
                                try:
                                    st.markdown(f"**{uploaded_at.strftime('%d %b %Y')}**")
                                except Exception:
                                    st.markdown(f"**{str(uploaded_at)[:10]}**")
                            else:
                                st.markdown(f"**{display_month}**")
                        with c2:
                            amt_label = "REIMBURSEMENT AMOUNT" if inv["INVOICE_TYPE"] == "Reimbursement" else "AMOUNT"
                            st.caption(amt_label)
                            amt = inv.get("TOTAL_AMOUNT")
                            st.markdown(f"**₹ {amt:,.2f}**" if amt and amt == amt else "**—**")


# ─── LEGAL ADMIN PORTAL ──────────────────────────────────────────────────────

def legal_admin_portal():
    import pandas as pd
    import string, random

    user = st.session_state["user"]

    # Navy theme CSS - hide sidebar, use top nav
    st.markdown("""
    <style>
        section[data-testid="stSidebar"] { display: none !important; }
        .block-container { background-color: #f0f4f8; }
        .portal-header { width: 100%; background: linear-gradient(90deg, #0a0f1e, #13203d, #1f3d6d); padding: 20px 30px; display: flex; align-items: center; gap: 16px; box-shadow: 0 4px 20px rgba(10,15,30,0.4); border-bottom: 3px solid #2c4e8a; margin-bottom: 25px; border-radius: 8px; }
        .portal-header h2 { font-size: 24px; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 0.5px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        .portal-header p { font-size: 13px; color: #b0c4de; margin: 4px 0 0 0; font-weight: 300; letter-spacing: 0.3px; }
        .stButton button { border-radius: 8px; font-weight: 600; background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; border: none !important; transition: all 0.3s ease; }
        .stButton button:hover { background: linear-gradient(90deg, #1a3359, #1f3d6d, #2c4e8a) !important; transform: translateY(-2px); }
        .stForm button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; border: none !important; border-radius: 8px; font-weight: 600; padding: 10px 20px; }
        .stTabs [data-baseweb="tab-list"] { gap: 2px; background-color: transparent; padding: 0; border-bottom: 2px solid #1f3d6d; }
        .stTabs [data-baseweb="tab"] { padding: 10px 20px; background-color: #e6ecf5; color: #0a0f1e; border: none; font-weight: 500; transition: all 0.3s; margin-right: 2px; }
        .stTabs [data-baseweb="tab"]:hover { background-color: #cbd6e6; }
        .stTabs [aria-selected="true"] { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; color: white !important; font-weight: 600; }
        .stTextInput > div > div > input, .stSelectbox > div > div > div { border-radius: 8px; border: 1px solid #cbd6e6; background-color: white; transition: all 0.3s; }
        .stAlert { border-radius: 10px; border-left: 5px solid #1f3d6d; background: white; }
        .stDownloadButton button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; }
        .stProgress > div > div { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; }
        hr { border-color: #1f3d6d !important; opacity: 0.2; }
    </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown(
        f"""<div class="portal-header">
            <div style="flex:1;">
                <h2>Legal Administration Portal</h2>
                <p>Manage consultants and employee onboarding</p>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Top action buttons (right-aligned)
    nav_spacer, nav_pwd, nav_logout = st.columns([6, 2, 1.5])
    with nav_pwd:
        if st.button(":material/lock_reset: Change Password", use_container_width=True, key="legal_chg_pwd"):
            st.session_state["show_admin_pwd_change"] = not st.session_state.get("show_admin_pwd_change", False)
    with nav_logout:
        if st.button(":material/logout: Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # Collapsible change password section
    if st.session_state.get("show_admin_pwd_change"):
        with st.expander(":material/lock_reset: Change Password", expanded=True):
            with st.form("admin_change_pwd_form_legal"):
                cp1, cp2, cp3 = st.columns(3)
                with cp1:
                    cur_pwd = st.text_input("Current Password", type="password", key="legal_cur_pwd")
                with cp2:
                    new_pwd = st.text_input("New Password", type="password", key="legal_new_pwd")
                with cp3:
                    confirm_pwd = st.text_input("Confirm New Password", type="password", key="legal_confirm_pwd")
                if st.form_submit_button("Update Password", type="primary", use_container_width=True):
                    if not cur_pwd or not new_pwd or not confirm_pwd:
                        st.error("All fields are required.")
                    elif new_pwd != confirm_pwd:
                        st.error("New passwords do not match.")
                    elif len(new_pwd) < 8:
                        st.error("Password must be at least 8 characters.")
                    else:
                        cur_hash = hash_password(cur_pwd)
                        verify = conn.query(
                            "SELECT USER_ID FROM INVOICE_MGMT.PUBLIC.ADMIN_USERS WHERE USER_ID = :1 AND PASSWORD_HASH = :2",
                            params=[int(user["USER_ID"]), cur_hash],
                        )
                        if len(verify) == 0:
                            st.error("Current password is incorrect.")
                        else:
                            new_hash = hash_password(new_pwd)
                            session.sql(
                                f"UPDATE INVOICE_MGMT.PUBLIC.ADMIN_USERS SET PASSWORD_HASH = '{new_hash}', UPDATED_AT = {IST_SQL} WHERE USER_ID = {int(user['USER_ID'])}"
                            ).collect()
                            st.success("Password changed successfully!")
                            st.session_state.pop("show_admin_pwd_change", None)

    # ─── METRICS ─────────────────────────────────────────────────────────────
    total_consultants = conn.query("SELECT COUNT(*) AS CNT FROM INVOICE_MGMT.PUBLIC.CONSULTANTS").iloc[0]["CNT"]
    active_consultants = conn.query("SELECT COUNT(*) AS CNT FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE IS_ACTIVE = TRUE").iloc[0]["CNT"]
    inactive_consultants = total_consultants - active_consultants

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total Consultants", total_consultants)
    with m2:
        st.metric("Active", active_consultants)
    with m3:
        st.metric("Inactive", inactive_consultants)

    tab_create, tab_view = st.tabs([
        ":material/person_add: Create Consultant/Employee",
        ":material/group: All Consultants",
    ])

    # ─── CREATE CONSULTANT TAB ────────────────────────────────────────────────
    with tab_create:
        st.subheader("Create New Consultant / Employee")
        st.info("For consultants, the ID must start with **ICT** (e.g. ICT001, ICT-SMITH). Rates can be multiple separated by semicolons (e.g. 1000;2000 — first is primary).")

        single_tab, bulk_tab = st.tabs(["Single Entry", "Bulk Upload (CSV)"])

        with single_tab:
            with st.form("create_consultant_form"):
                fc1, fc2 = st.columns(2)
                with fc1:
                    c_id = st.text_input("Consultant ID *", placeholder="e.g. ICT001 (must start with ICT)")
                    c_name = st.text_input("Full Name *", placeholder="e.g. John Doe")
                    c_email = st.text_input("Email *", placeholder="e.g. john@example.com")
                    c_mobile = st.text_input("Mobile No * (10 digits)", placeholder="e.g. 9876543210")
                with fc2:
                    c_doj = st.date_input("Date of Joining *", value=now_ist().date())
                    c_rates = st.text_input("Rate(s) Per Day *", placeholder="e.g. 5000 or 5000;3000 (semicolon separated)")
                    c_pan = st.text_input("PAN Card *", placeholder="e.g. ABCDE1234F")
                    c_gst = st.text_input("GST (optional)", placeholder="e.g. 22AAAAA0000A1Z5")

                submitted = st.form_submit_button("Create Consultant", type="primary", use_container_width=True)

                if submitted:
                    import re
                    errors = []
                    if not c_id:
                        errors.append("Consultant ID is required.")
                    elif not c_id.upper().startswith("ICT"):
                        errors.append("Consultant ID must start with **ICT**.")
                    if not c_name:
                        errors.append("Name is required.")
                    if not c_email:
                        errors.append("Email is required.")
                    elif not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', c_email):
                        errors.append("Please enter a valid email address.")
                    if not c_mobile:
                        errors.append("Mobile number is required.")
                    elif not re.match(r'^\d{10}$', c_mobile.strip()):
                        errors.append("Mobile number must be exactly 10 digits (no +91 or spaces).")
                    if not c_pan:
                        errors.append("PAN Card is required.")
                    if not c_rates:
                        errors.append("At least one rate per day is required.")
                    else:
                        rate_parts = [r.strip() for r in c_rates.split(";") if r.strip()]
                        for rp in rate_parts:
                            try:
                                rv = float(rp)
                                if rv <= 0:
                                    errors.append(f"Rate '{rp}' must be greater than 0.")
                            except ValueError:
                                errors.append(f"Rate '{rp}' is not a valid number.")

                    if errors:
                        for err in errors:
                            st.error(err)
                    else:
                        existing = conn.query(
                            "SELECT CONSULTANT_ID FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE CONSULTANT_ID = :1",
                            params=[c_id.upper()],
                        )
                        if len(existing) > 0:
                            st.error(f"Consultant ID '{c_id.upper()}' already exists.")
                        else:
                            safe_id = c_id.upper().replace("'", "''")
                            safe_name = c_name.replace("'", "''")
                            safe_email = c_email.replace("'", "''")
                            safe_mobile = c_mobile.strip().replace("'", "''")
                            safe_pan = c_pan.replace("'", "''")
                            safe_gst = c_gst.replace("'", "''") if c_gst else ""

                            # Generate temporary password
                            temp_pwd = "".join(random.choices(string.ascii_letters + string.digits + "!@#$", k=10))
                            pwd_hash = conn.query("SELECT SHA2(:1) AS H", params=[temp_pwd]).iloc[0]["H"]

                            # Insert consultant with auth credentials
                            session.sql(f"""
                                INSERT INTO INVOICE_MGMT.PUBLIC.CONSULTANTS
                                (CONSULTANT_ID, NAME, DATE_OF_JOINING, EMAIL, MOBILE, PAN_CARD, GST, IS_ACTIVE, CREATED_BY, USERNAME, PASSWORD_HASH, IS_TEMP_PASSWORD)
                                VALUES ('{safe_id}', '{safe_name}', '{c_doj}', '{safe_email}', '{safe_mobile}',
                                        '{safe_pan}', '{safe_gst}', TRUE, '{user["USERNAME"]}', '{safe_id}', '{pwd_hash}', TRUE)
                            """).collect()

                            # Insert rates - first is primary, rest are secondary
                            rate_parts = [r.strip() for r in c_rates.split(";") if r.strip()]
                            for idx, rp in enumerate(rate_parts):
                                is_primary = "TRUE" if idx == 0 else "FALSE"
                                session.sql(f"""
                                    INSERT INTO INVOICE_MGMT.PUBLIC.CONSULTANT_RATES
                                    (CONSULTANT_ID, RATE_PER_DAY, EFFECTIVE_FROM, IS_PRIMARY, CREATED_BY)
                                    VALUES ('{safe_id}', {float(rp)}, '{c_doj}', {is_primary}, '{user["USERNAME"]}')
                                """).collect()

                            # Store temp password for audit
                            session.sql(f"""
                                INSERT INTO INVOICE_MGMT.PUBLIC.TEMP_PASSWORDS
                                (CONSULTANT_ID, NAME, TEMP_PASSWORD, ISSUED_BY)
                                VALUES ('{safe_id}', '{safe_name}', '{temp_pwd}', '{user["USERNAME"]}')
                            """).collect()

                            # Send welcome email
                            email_sent = send_welcome_email(c_email, c_name, safe_id, temp_pwd)

                            st.success(f"Consultant **{c_name}** ({safe_id}) created successfully!")
                            if email_sent:
                                st.success(f"Welcome email sent to **{c_email}** with login credentials.")
                            else:
                                st.warning("Could not send welcome email. Please share credentials manually.")
                            st.info(f"""
                            **Login Credentials (share securely):**
                            - Username: `{safe_id}`
                            - Temporary Password: `{temp_pwd}`

                            *Consultant must change password on first login.*
                            """)

        with bulk_tab:
            st.markdown("""
            **CSV format required:**
            | CONSULTANT_ID | NAME | DATE_OF_JOINING | EMAIL | MOBILE | RATE_PER_DAY | PAN_CARD | GST |
            |---|---|---|---|---|---|---|---|
            | ICT001 | John Doe | 2026-06-01 | john@ex.com | 9876543210 | 5000 or 5000;3000 | ABCDE1234F | (optional) |

            **Notes:** Mobile must be 10 digits. Rate can be semicolon-separated for multiple rates.
            """)

            csv_file = st.file_uploader("Upload Consultants CSV", type=["csv"], key="bulk_consultants_csv")

            if csv_file is not None:
                import re
                try:
                    df = pd.read_csv(csv_file, dtype=str)
                    df.columns = [c.upper().strip() for c in df.columns]
                    st.dataframe(df, use_container_width=True, hide_index=True)

                    required = ["CONSULTANT_ID", "NAME", "EMAIL", "MOBILE", "RATE_PER_DAY", "PAN_CARD"]
                    missing = [c for c in required if c not in df.columns]

                    if missing:
                        st.error(f"Missing columns: {', '.join(missing)}")
                    else:
                        # Validate
                        invalid_ids = df[~df["CONSULTANT_ID"].str.upper().str.startswith("ICT")]
                        invalid_emails = df[~df["EMAIL"].str.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', na=False)]
                        invalid_mobiles = df[~df["MOBILE"].str.strip().str.match(r'^\d{10}$', na=False)]

                        has_errors = False
                        if len(invalid_ids) > 0:
                            st.error(f"{len(invalid_ids)} row(s) have IDs that don't start with 'ICT'.")
                            has_errors = True
                        if len(invalid_emails) > 0:
                            st.error(f"{len(invalid_emails)} row(s) have invalid email addresses.")
                            has_errors = True
                        if len(invalid_mobiles) > 0:
                            st.error(f"{len(invalid_mobiles)} row(s) have invalid mobile numbers (must be 10 digits, no +91).")
                            has_errors = True

                        if not has_errors:
                            st.success(f"**{len(df)} rows** validated and ready to import.")
                            if st.button("Create All Consultants", type="primary", use_container_width=True):
                                created = 0
                                skipped = 0
                                credentials_list = []
                                for _, row in df.iterrows():
                                    cid = str(row["CONSULTANT_ID"]).strip().upper().replace("'", "''")
                                    ex = conn.query("SELECT CONSULTANT_ID FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE CONSULTANT_ID = :1", params=[cid])
                                    if len(ex) > 0:
                                        skipped += 1
                                        continue

                                    name = str(row["NAME"]).strip().replace("'", "''")
                                    email = str(row["EMAIL"]).strip().replace("'", "''")
                                    mobile = str(row["MOBILE"]).strip().replace("'", "''")
                                    rates_str = str(row["RATE_PER_DAY"]).strip()
                                    pan = str(row["PAN_CARD"]).strip().replace("'", "''")
                                    gst = str(row.get("GST", "")).strip().replace("'", "''") if "GST" in df.columns and pd.notna(row.get("GST")) else ""
                                    doj = str(row.get("DATE_OF_JOINING", now_ist().date())).strip() if "DATE_OF_JOINING" in df.columns and pd.notna(row.get("DATE_OF_JOINING")) else str(now_ist().date())

                                    temp_pwd = "".join(random.choices(string.ascii_letters + string.digits + "!@#$", k=10))
                                    pwd_hash = conn.query("SELECT SHA2(:1) AS H", params=[temp_pwd]).iloc[0]["H"]

                                    # Insert consultant with auth
                                    session.sql(f"""
                                        INSERT INTO INVOICE_MGMT.PUBLIC.CONSULTANTS
                                        (CONSULTANT_ID, NAME, DATE_OF_JOINING, EMAIL, MOBILE, PAN_CARD, GST, IS_ACTIVE, CREATED_BY, USERNAME, PASSWORD_HASH, IS_TEMP_PASSWORD)
                                        VALUES ('{cid}', '{name}', '{doj}', '{email}', '{mobile}', '{pan}', '{gst}', TRUE, '{user["USERNAME"]}', '{cid}', '{pwd_hash}', TRUE)
                                    """).collect()

                                    # Insert rates (semicolon separated) - first is primary
                                    rate_parts = [r.strip() for r in rates_str.split(";") if r.strip()]
                                    for idx, rp in enumerate(rate_parts):
                                        try:
                                            is_primary = "TRUE" if idx == 0 else "FALSE"
                                            session.sql(f"""
                                                INSERT INTO INVOICE_MGMT.PUBLIC.CONSULTANT_RATES
                                                (CONSULTANT_ID, RATE_PER_DAY, EFFECTIVE_FROM, IS_PRIMARY, CREATED_BY)
                                                VALUES ('{cid}', {float(rp)}, '{doj}', {is_primary}, '{user["USERNAME"]}')
                                            """).collect()
                                        except Exception:
                                            pass

                                    session.sql(f"""
                                        INSERT INTO INVOICE_MGMT.PUBLIC.TEMP_PASSWORDS
                                        (CONSULTANT_ID, NAME, TEMP_PASSWORD, ISSUED_BY)
                                        VALUES ('{cid}', '{name}', '{temp_pwd}', '{user["USERNAME"]}')
                                    """).collect()

                                    # Send welcome email
                                    send_welcome_email(email, name, cid, temp_pwd)

                                    credentials_list.append({"Consultant_ID": cid, "Name": name, "Username": cid, "Temp_Password": temp_pwd})
                                    created += 1

                                st.success(f"Created {created} consultant(s). Skipped {skipped} (already exist).")
                                if credentials_list:
                                    st.subheader("Generated Credentials")
                                    creds_df = pd.DataFrame(credentials_list)
                                    st.dataframe(creds_df, use_container_width=True, hide_index=True)
                                    st.download_button(
                                        "Download Credentials CSV",
                                        data=creds_df.to_csv(index=False),
                                        file_name="consultant_credentials.csv",
                                        mime="text/csv",
                                        use_container_width=True,
                                    )
                except Exception as e:
                    st.error(f"Error reading CSV: {e}")

    # ─── VIEW ALL CONSULTANTS TAB ────────────────────────────────────────────
    with tab_view:
        st.subheader("Consultant Directory")

        # Search / filter - aligned in single row
        search_term = st.text_input("Search", placeholder="Search by ID, Name, Email, PAN, Mobile...", label_visibility="collapsed")
        status_filter = st.radio("Status", ["All", "Active", "Inactive"], horizontal=True, label_visibility="collapsed")

        where_clauses = []
        if search_term:
            safe_search = search_term.replace("'", "''")
            where_clauses.append(
                f"(c.CONSULTANT_ID ILIKE '%{safe_search}%' OR c.NAME ILIKE '%{safe_search}%' "
                f"OR c.EMAIL ILIKE '%{safe_search}%' OR c.PAN_CARD ILIKE '%{safe_search}%' "
                f"OR c.MOBILE ILIKE '%{safe_search}%' OR c.GST ILIKE '%{safe_search}%')"
            )
        if status_filter == "Active":
            where_clauses.append("c.IS_ACTIVE = TRUE")
        elif status_filter == "Inactive":
            where_clauses.append("c.IS_ACTIVE = FALSE")

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        consultants_df = session.sql(f"""
            SELECT c.CONSULTANT_ID, c.NAME, c.DATE_OF_JOINING, c.EMAIL, c.MOBILE,
                   c.PAN_CARD, c.GST, c.IS_ACTIVE, c.IS_TEMP_PASSWORD,
                   LISTAGG(CASE WHEN r.IS_PRIMARY = TRUE THEN r.RATE_PER_DAY::VARCHAR END, '; ') WITHIN GROUP (ORDER BY r.RATE_ID ASC) AS PRIMARY_RATES,
                   LISTAGG(CASE WHEN r.IS_PRIMARY = FALSE THEN r.RATE_PER_DAY::VARCHAR END, '; ') WITHIN GROUP (ORDER BY r.RATE_ID ASC) AS SECONDARY_RATES,
                   c.UPDATED_BY, c.UPDATED_AT,
                   tp.TEMP_PASSWORD,
                   tp.ISSUED_AT AS PWD_ISSUED_AT
            FROM INVOICE_MGMT.PUBLIC.CONSULTANTS c
            LEFT JOIN INVOICE_MGMT.PUBLIC.CONSULTANT_RATES r
                ON c.CONSULTANT_ID = r.CONSULTANT_ID AND r.EFFECTIVE_TO IS NULL
            LEFT JOIN INVOICE_MGMT.PUBLIC.TEMP_PASSWORDS tp
                ON c.CONSULTANT_ID = tp.CONSULTANT_ID
                AND tp.ISSUED_AT = (SELECT MAX(ISSUED_AT) FROM INVOICE_MGMT.PUBLIC.TEMP_PASSWORDS WHERE CONSULTANT_ID = c.CONSULTANT_ID)
            {where_sql}
            GROUP BY c.CONSULTANT_ID, c.NAME, c.DATE_OF_JOINING, c.EMAIL, c.MOBILE,
                     c.PAN_CARD, c.GST, c.IS_ACTIVE, c.IS_TEMP_PASSWORD, c.UPDATED_BY, c.UPDATED_AT,
                     tp.TEMP_PASSWORD, tp.ISSUED_AT
            ORDER BY c.NAME
        """).to_pandas()

        if len(consultants_df) == 0:
            st.info("No consultants found.")
        else:
            st.caption(f"Showing {len(consultants_df)} consultant(s)")

            for _, row in consultants_df.iterrows():
                status_dot = "🟢" if row["IS_ACTIVE"] else "🔴"
                status_text = "Active" if row["IS_ACTIVE"] else "Inactive"

                with st.container(border=True):
                    # Header: Name, ID, Status, Edit
                    h1, h2, h3 = st.columns([5, 2, 1])
                    with h1:
                        st.markdown(f"**{row['NAME']}** &nbsp; `{row['CONSULTANT_ID']}`")
                    with h2:
                        st.markdown(f"{status_dot} {status_text}")
                    with h3:
                        edit_key = f"edit_{row['CONSULTANT_ID']}"
                        if st.button(":material/edit:", key=edit_key, use_container_width=True):
                            st.session_state["editing_consultant"] = row["CONSULTANT_ID"]
                            st.rerun()

                    # Details grid
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1:
                        st.caption("EMAIL")
                        st.markdown(f"{row['EMAIL'] or '—'}")
                    with c2:
                        st.caption("MOBILE")
                        st.markdown(f"{row['MOBILE'] or '—'}")
                    with c3:
                        st.caption("DOJ")
                        doj = row["DATE_OF_JOINING"]
                        st.markdown(f"{doj.strftime('%d %b %Y') if doj and doj == doj else '—'}")
                    with c4:
                        st.caption("RATE/DAY")
                        primary = row['PRIMARY_RATES'] if row['PRIMARY_RATES'] else ""
                        secondary = row['SECONDARY_RATES'] if row['SECONDARY_RATES'] else ""
                        if primary:
                            st.markdown(f"₹ **{primary}** (Primary)")
                        if secondary:
                            sec_list = [r.strip() for r in secondary.split(";") if r.strip()]
                            st.caption(f"Secondary: {', '.join(['₹'+r for r in sec_list])}")
                        if not primary and not secondary:
                            st.markdown("—")
                    with c5:
                        st.caption("PAN")
                        st.markdown(f"{row['PAN_CARD'] or '—'}")

                    # Temp password row - show if user hasn't changed pwd yet (IS_TEMP_PASSWORD=True)
                    # and password was issued within 24hrs
                    show_pwd = False
                    if row.get("IS_TEMP_PASSWORD") and row.get("TEMP_PASSWORD"):
                        pwd_issued = row.get("PWD_ISSUED_AT")
                        if pwd_issued and pwd_issued == pwd_issued:
                            try:
                                if (now_ist() - pwd_issued) < timedelta(hours=24):
                                    show_pwd = True
                            except Exception:
                                show_pwd = True
                        else:
                            show_pwd = True

                    if show_pwd:
                        pwd_key = f"show_pwd_{row['CONSULTANT_ID']}"
                        p1, p2 = st.columns([5, 1])
                        with p1:
                            if st.session_state.get(pwd_key):
                                st.markdown(
                                    f'<div style="background:#FFF8E1; padding:6px 12px; border-radius:6px; font-size:0.85rem;">'
                                    f'🔑 <strong>Temp Password:</strong> <code>{row["TEMP_PASSWORD"]}</code></div>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    f'<div style="background:#FFF8E1; padding:6px 12px; border-radius:6px; font-size:0.85rem;">'
                                    f'🔑 <strong>Temp Password:</strong> ••••••••••</div>',
                                    unsafe_allow_html=True,
                                )
                        with p2:
                            if st.button("👁" if not st.session_state.get(pwd_key) else "🙈", key=f"toggle_{row['CONSULTANT_ID']}", use_container_width=True):
                                st.session_state[pwd_key] = not st.session_state.get(pwd_key, False)
                                st.rerun()

            # ─── EDIT CONSULTANT DIALOG ──────────────────────────────────────
            if st.session_state.get("editing_consultant"):
                edit_id = st.session_state["editing_consultant"]
                edit_row = session.sql(f"""
                    SELECT * FROM INVOICE_MGMT.PUBLIC.CONSULTANTS WHERE CONSULTANT_ID = '{edit_id}'
                """).to_pandas()

                if len(edit_row) > 0:
                    edit_row = edit_row.iloc[0]
                    st.divider()
                    st.subheader(f"Editing: {edit_row['NAME']} ({edit_id})")

                    # Get current rates (active ones with no EFFECTIVE_TO)
                    current_rates = session.sql(f"""
                        SELECT RATE_PER_DAY, IS_PRIMARY FROM INVOICE_MGMT.PUBLIC.CONSULTANT_RATES
                        WHERE CONSULTANT_ID = '{edit_id}' AND EFFECTIVE_TO IS NULL
                        ORDER BY IS_PRIMARY DESC, RATE_ID ASC
                    """).to_pandas()
                    # Build rates string: primary first, then secondary
                    primary_rates = current_rates[current_rates["IS_PRIMARY"] == True]["RATE_PER_DAY"].tolist()
                    secondary_rates = current_rates[current_rates["IS_PRIMARY"] == False]["RATE_PER_DAY"].tolist()
                    all_rates = primary_rates + secondary_rates
                    current_rates_str = ";".join([str(int(r) if r == int(r) else r) for r in all_rates]) if all_rates else ""

                    with st.form("edit_consultant_form"):
                        import re
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            e_name = st.text_input("Name", value=edit_row["NAME"] or "")
                            e_email = st.text_input("Email", value=edit_row["EMAIL"] or "")
                            e_mobile = st.text_input("Mobile (10 digits)", value=edit_row["MOBILE"] or "")
                            e_doj = st.date_input("Date of Joining", value=edit_row["DATE_OF_JOINING"] if edit_row["DATE_OF_JOINING"] and edit_row["DATE_OF_JOINING"] == edit_row["DATE_OF_JOINING"] else None)
                        with ec2:
                            e_pan = st.text_input("PAN Card", value=edit_row["PAN_CARD"] or "")
                            e_gst = st.text_input("GST (optional)", value=edit_row["GST"] or "")
                            e_active = st.selectbox("Status", ["Active", "Inactive"], index=0 if edit_row["IS_ACTIVE"] else 1)
                            e_rates = st.text_input("Rate(s) Per Day (semicolon separated)", value=current_rates_str, help="e.g. 5000;3000 — first is primary")

                        btn_col1, btn_col2 = st.columns(2)
                        with btn_col1:
                            save_btn = st.form_submit_button("Save Changes", type="primary", use_container_width=True)
                        with btn_col2:
                            cancel_btn = st.form_submit_button("Cancel", use_container_width=True)

                        if cancel_btn:
                            st.session_state.pop("editing_consultant", None)
                            st.rerun()

                        if save_btn:
                            errors = []
                            if e_email and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', e_email):
                                errors.append("Please enter a valid email address.")
                            if e_mobile and not re.match(r'^\d{10}$', e_mobile.strip()):
                                errors.append("Mobile must be exactly 10 digits.")
                            if not e_rates.strip():
                                errors.append("At least one rate is required.")
                            else:
                                rate_parts = [r.strip() for r in e_rates.split(";") if r.strip()]
                                for rp in rate_parts:
                                    try:
                                        if float(rp) <= 0:
                                            errors.append(f"Rate '{rp}' must be > 0.")
                                    except ValueError:
                                        errors.append(f"Rate '{rp}' is not valid.")

                            if errors:
                                for err in errors:
                                    st.error(err)
                            else:
                                safe_name = e_name.replace("'", "''")
                                safe_email = e_email.replace("'", "''")
                                safe_mobile = e_mobile.strip().replace("'", "''")
                                safe_pan = e_pan.replace("'", "''")
                                safe_gst = e_gst.replace("'", "''")
                                is_active = "TRUE" if e_active == "Active" else "FALSE"
                                doj_sql = f"'{e_doj}'" if e_doj else "NULL"

                                session.sql(f"""
                                    UPDATE INVOICE_MGMT.PUBLIC.CONSULTANTS
                                    SET NAME = '{safe_name}', EMAIL = '{safe_email}', MOBILE = '{safe_mobile}',
                                        PAN_CARD = '{safe_pan}', GST = '{safe_gst}', IS_ACTIVE = {is_active},
                                        DATE_OF_JOINING = {doj_sql},
                                        UPDATED_BY = '{user["USERNAME"]}', UPDATED_AT = {IST_SQL}
                                    WHERE CONSULTANT_ID = '{edit_id}'
                                """).collect()

                                # Track field changes for history
                                old_vals = {
                                    "NAME": edit_row["NAME"], "EMAIL": edit_row["EMAIL"],
                                    "MOBILE": edit_row["MOBILE"], "PAN_CARD": edit_row["PAN_CARD"],
                                    "GST": edit_row["GST"], "IS_ACTIVE": str(edit_row["IS_ACTIVE"]),
                                }
                                new_vals = {
                                    "NAME": e_name, "EMAIL": e_email,
                                    "MOBILE": e_mobile.strip(), "PAN_CARD": e_pan,
                                    "GST": e_gst, "IS_ACTIVE": is_active,
                                }
                                for field, old_val in old_vals.items():
                                    new_val = new_vals[field]
                                    if str(old_val or "") != str(new_val or ""):
                                        log_history("CONSULTANTS", edit_id, field, old_val, new_val, user["USERNAME"])

                                # Handle rate changes: close old rates (set EFFECTIVE_TO) and insert new
                                new_rate_parts = [r.strip() for r in e_rates.split(";") if r.strip()]
                                new_rate_values = [float(rp) for rp in new_rate_parts]

                                if new_rate_values != [float(r) for r in all_rates]:
                                    log_history("CONSULTANT_RATES", edit_id, "RATES",
                                               ";".join([str(r) for r in all_rates]),
                                               ";".join([str(r) for r in new_rate_values]),
                                               user["USERNAME"])

                                    # Close existing active rates by setting EFFECTIVE_TO
                                    today = now_ist().date()
                                    session.sql(f"""
                                        UPDATE INVOICE_MGMT.PUBLIC.CONSULTANT_RATES
                                        SET EFFECTIVE_TO = '{today}'
                                        WHERE CONSULTANT_ID = '{edit_id}' AND EFFECTIVE_TO IS NULL
                                    """).collect()

                                    # Insert new rates - first is primary
                                    for idx, rp in enumerate(new_rate_parts):
                                        is_primary = "TRUE" if idx == 0 else "FALSE"
                                        session.sql(f"""
                                            INSERT INTO INVOICE_MGMT.PUBLIC.CONSULTANT_RATES
                                            (CONSULTANT_ID, RATE_PER_DAY, EFFECTIVE_FROM, IS_PRIMARY, CREATED_BY)
                                            VALUES ('{edit_id}', {float(rp)}, '{today}', {is_primary}, '{user["USERNAME"]}')
                                        """).collect()

                                st.session_state.pop("editing_consultant", None)
                                st.success("Consultant updated successfully!")
                                st.rerun()



# ─── ACCOUNTING PORTAL ────────────────────────────────────────────────────────

def accounting_portal():
    import zipfile
    import io
    import pandas as pd

    user = st.session_state["user"]

    with st.sidebar:
        st.markdown(f"**{user.get('USERNAME', 'Admin')}**")
        st.caption("Accounting & Finance")
        st.divider()
        if st.button(":material/lock_reset: Change Password", use_container_width=True, key="acct_chg_pwd"):
            st.session_state["show_acct_pwd_change"] = True
        if st.button(":material/logout: Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        if st.session_state.get("show_acct_pwd_change"):
            st.divider()
            with st.form("admin_change_pwd_form_acct"):
                st.markdown("**Change Password**")
                cur_pwd = st.text_input("Current Password", type="password", key="acct_cur_pwd")
                new_pwd = st.text_input("New Password", type="password", key="acct_new_pwd")
                confirm_pwd = st.text_input("Confirm New Password", type="password", key="acct_confirm_pwd")
                if st.form_submit_button("Update", type="primary", use_container_width=True):
                    if not cur_pwd or not new_pwd or not confirm_pwd:
                        st.error("All fields are required.")
                    elif new_pwd != confirm_pwd:
                        st.error("New passwords do not match.")
                    elif len(new_pwd) < 8:
                        st.error("Password must be at least 8 characters.")
                    else:
                        cur_hash = hash_password(cur_pwd)
                        verify = conn.query(
                            "SELECT USER_ID FROM INVOICE_MGMT.PUBLIC.ADMIN_USERS WHERE USER_ID = :1 AND PASSWORD_HASH = :2",
                            params=[int(user["USER_ID"]), cur_hash],
                        )
                        if len(verify) == 0:
                            st.error("Current password is incorrect.")
                        else:
                            new_hash = hash_password(new_pwd)
                            session.sql(
                                f"UPDATE INVOICE_MGMT.PUBLIC.ADMIN_USERS SET PASSWORD_HASH = '{new_hash}', UPDATED_AT = {IST_SQL} WHERE USER_ID = {int(user['USER_ID'])}"
                            ).collect()
                            st.success("Password changed successfully!")
                            st.session_state.pop("show_acct_pwd_change", None)

    # Navy theme CSS
    st.markdown("""
    <style>
        .block-container { background-color: #f0f4f8; }
        .portal-header { width: 100%; background: linear-gradient(90deg, #0a0f1e, #13203d, #1f3d6d); padding: 20px 30px; display: flex; align-items: center; gap: 16px; box-shadow: 0 4px 20px rgba(10,15,30,0.4); border-bottom: 3px solid #2c4e8a; margin-bottom: 25px; border-radius: 8px; }
        .portal-header h2 { font-size: 24px; font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: 0.5px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        .portal-header p { font-size: 13px; color: #b0c4de; margin: 4px 0 0 0; font-weight: 300; letter-spacing: 0.3px; }
        .stButton button { border-radius: 8px; font-weight: 600; background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; border: none !important; transition: all 0.3s ease; }
        .stButton button:hover { background: linear-gradient(90deg, #1a3359, #1f3d6d, #2c4e8a) !important; transform: translateY(-2px); }
        .stForm button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; border: none !important; border-radius: 8px; font-weight: 600; padding: 10px 20px; }
        .stTabs [data-baseweb="tab-list"] { gap: 2px; background-color: transparent; padding: 0; border-bottom: 2px solid #1f3d6d; }
        .stTabs [data-baseweb="tab"] { padding: 10px 20px; background-color: #e6ecf5; color: #0a0f1e; border: none; font-weight: 500; transition: all 0.3s; margin-right: 2px; }
        .stTabs [data-baseweb="tab"]:hover { background-color: #cbd6e6; }
        .stTabs [aria-selected="true"] { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; color: white !important; font-weight: 600; }
        .stTextInput > div > div > input, .stSelectbox > div > div > div { border-radius: 8px; border: 1px solid #cbd6e6; background-color: white; transition: all 0.3s; }
        .stAlert { border-radius: 10px; border-left: 5px solid #1f3d6d; background: white; }
        .stDownloadButton button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a, #3a5f9c) !important; color: white !important; }
        [data-testid="stSidebar"] { background: linear-gradient(135deg, #f0f4f8, #e6ecf5); border-right: 2px solid #1f3d6d; }
        [data-testid="stSidebar"] .stButton button { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; }
        .stProgress > div > div { background: linear-gradient(90deg, #1f3d6d, #2c4e8a) !important; }
        hr { border-color: #1f3d6d !important; opacity: 0.2; }
        .metric-card { background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border-radius: 12px; padding: 1.2rem; border: 1px solid #e2e8f0; text-align: center; }
        .metric-card h3 { margin: 0; font-size: 1.8rem; color: #1f3d6d; }
        .metric-card p { margin: 0.2rem 0 0 0; font-size: 0.8rem; color: #64748B; }
        .fixed-footer { width: 100%; text-align: center; padding: 8px 10px; background: white !important; border-top: 2px solid #2c4e8a; font-size: 13px; font-weight: 300; letter-spacing: 0.3px; margin-top: 30px; }
        .fixed-footer p { margin: 0; opacity: 0.9; color: #13203d; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(
        f"""<div class="portal-header">
            <h2>Accounting & Finance Portal</h2>
            <p>Invoice verification, payment processing & financial reports</p>
        </div>""",
        unsafe_allow_html=True,
    )

    # Helper: month picker (starting from June 2025)
    def month_picker(key_prefix):
        month_options = []
        month_values = []
        start_year, start_month = 2026, 6
        now = now_ist()
        y, m = now.year, now.month
        while (y, m) >= (start_year, start_month):
            month_values.append(f"{y}-{m:02d}")
            month_options.append(datetime(y, m, 1).strftime("%B %Y"))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        idx = st.selectbox("Select Month", range(len(month_options)), format_func=lambda x: month_options[x], key=f"{key_prefix}_month")
        return month_values[idx], month_options[idx]

    tab_submission, tab_invoices, tab_reports = st.tabs([
        ":material/assignment_turned_in: Submission Status",
        ":material/description: Invoices",
        ":material/analytics: Reports",
    ])

    # ─── INVOICE SUBMISSION STATUS TAB ────────────────────────────────────────
    with tab_submission:
        st.markdown("#### Invoice Submission Status")
        st.caption("Month-wise overview of consultant invoice submissions")

        sel_month_sub, display_month_sub = month_picker("submission_status")

        submission_data = session.sql(f"""
            SELECT c.CONSULTANT_ID, c.NAME AS FULL_NAME, c.EMAIL, c.IS_ACTIVE,
                   i.INVOICE_ID, i.STATUS AS INVOICE_STATUS,
                   CASE WHEN i.INVOICE_ID IS NOT NULL THEN 'Submitted' ELSE 'Not Submitted' END AS SUBMISSION_STATUS
            FROM INVOICE_MGMT.PUBLIC.CONSULTANTS c
            LEFT JOIN INVOICE_MGMT.PUBLIC.INVOICES i
                ON c.CONSULTANT_ID = i.CONSULTANT_ID AND i.INVOICE_MONTH = '{sel_month_sub}'
            WHERE c.IS_ACTIVE = TRUE
            ORDER BY SUBMISSION_STATUS DESC, c.NAME
        """).to_pandas()

        if len(submission_data) == 0:
            st.info("No active consultants found.")
        else:
            total_active = len(submission_data)
            submitted = len(submission_data[submission_data["SUBMISSION_STATUS"] == "Submitted"])
            not_submitted = total_active - submitted

            # Status breakdown of submitted invoices
            under_process = len(submission_data[submission_data["INVOICE_STATUS"] == "UNDER PROCESS"])
            verified = len(submission_data[submission_data["INVOICE_STATUS"] == "DETAILS VERIFIED"])
            payment_proc = len(submission_data[submission_data["INVOICE_STATUS"] == "PAYMENT IN PROCESS"])
            paid = len(submission_data[submission_data["INVOICE_STATUS"] == "PAYMENT PROCESSED"])
            rejected = len(submission_data[submission_data["INVOICE_STATUS"] == "REJECTED"])

            # Metric cards
            k1, k2, k3 = st.columns(3)
            with k1:
                st.markdown(f'<div class="metric-card"><h3>{total_active}</h3><p>ACTIVE CONSULTANTS</p></div>', unsafe_allow_html=True)
            with k2:
                st.markdown(f'<div class="metric-card"><h3 style="color:#2E7D32;">{submitted}</h3><p>INVOICES SUBMITTED</p></div>', unsafe_allow_html=True)
            with k3:
                st.markdown(f'<div class="metric-card"><h3 style="color:#C62828;">{not_submitted}</h3><p>NOT SUBMITTED</p></div>', unsafe_allow_html=True)

            st.markdown("")

            # Charts
            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:
                st.markdown("##### Submission Overview")
                pie_data = pd.DataFrame({
                    "Category": ["Submitted", "Not Submitted"],
                    "Count": [submitted, not_submitted],
                })
                pie_data = pie_data[pie_data["Count"] > 0]
                st.bar_chart(pie_data.set_index("Category"), horizontal=True, color="#00897B")

            with chart_col2:
                st.markdown("##### Invoice Status Breakdown")
                status_chart_data = pd.DataFrame({
                    "Status": ["Under Process", "Verified", "Payment Processing", "Paid", "Rejected"],
                    "Count": [under_process, verified, payment_proc, paid, rejected],
                })
                status_chart_data = status_chart_data[status_chart_data["Count"] > 0]
                if len(status_chart_data) > 0:
                    st.bar_chart(status_chart_data.set_index("Status"), horizontal=True, color="#004D40")
                else:
                    st.info("No submitted invoices to break down.")

            # Detailed list
            st.divider()
            st.markdown("##### Consultant-wise Details")

            sub_tab_submitted, sub_tab_pending = st.tabs(["Submitted", "Not Submitted"])

            with sub_tab_submitted:
                submitted_df = submission_data[submission_data["SUBMISSION_STATUS"] == "Submitted"]
                if len(submitted_df) == 0:
                    st.info("No invoices submitted yet for this month.")
                else:
                    for _, row in submitted_df.iterrows():
                        badge_colors = {
                            "UNDER PROCESS": ("#FFF3E0", "#E65100"),
                            "DETAILS VERIFIED": ("#E3F2FD", "#1565C0"),
                            "PAYMENT IN PROCESS": ("#F3E5F5", "#6A1B9A"),
                            "PAYMENT PROCESSED": ("#E8F5E9", "#2E7D32"),
                            "REJECTED": ("#FFEBEE", "#C62828"),
                        }
                        bg, fg = badge_colors.get(row["INVOICE_STATUS"], ("#F5F5F5", "#333"))
                        with st.container(border=True):
                            r1, r2, r3 = st.columns([3, 2, 2])
                            with r1:
                                st.markdown(f"**{row['FULL_NAME']}**")
                                st.caption(f"ID: {row['CONSULTANT_ID']}")
                            with r2:
                                st.caption("EMAIL")
                                st.markdown(f"{row['EMAIL'] or '—'}")
                            with r3:
                                st.caption("INVOICE STATUS")
                                st.markdown(
                                    f'<span style="background:{bg}; color:{fg}; padding:4px 14px; border-radius:16px; font-size:0.8rem; font-weight:600;">{row["INVOICE_STATUS"]}</span>',
                                    unsafe_allow_html=True,
                                )

            with sub_tab_pending:
                pending_df = submission_data[submission_data["SUBMISSION_STATUS"] == "Not Submitted"]
                if len(pending_df) == 0:
                    st.success("All consultants have submitted their invoices!")
                else:
                    for _, row in pending_df.iterrows():
                        with st.container(border=True):
                            r1, r2, r3 = st.columns([3, 2, 2])
                            with r1:
                                st.markdown(f"**{row['FULL_NAME']}**")
                                st.caption(f"ID: {row['CONSULTANT_ID']}")
                            with r2:
                                st.caption("EMAIL")
                                st.markdown(f"{row['EMAIL'] or '—'}")
                            with r3:
                                st.markdown(":red[**Pending**]")

    # ─── INVOICES TAB ────────────────────────────────────────────────────────
    with tab_invoices:
        st.markdown("#### Invoice Review & Status Update")
        sel_month_inv, display_month_inv = month_picker("inv_review")

        invoices = session.sql(f"""
            SELECT i.INVOICE_ID, i.CONSULTANT_ID, c.NAME AS FULL_NAME, i.INVOICE_MONTH,
                   i.FILE_NAME, i.STATUS, i.WORKING_DAYS, i.UPLOADED_AT,
                   i.AI_EXTRACTED_DATA:"invoice_no"::STRING AS INVOICE_NO,
                   i.AI_EXTRACTED_DATA:"grand_total"::STRING AS INVOICE_AMOUNT,
                   i.AI_EXTRACTED_DATA:"name"::STRING AS INVOICE_NAME,
                   i.AI_EXTRACTED_DATA:"date"::STRING AS INVOICE_DATE,
                   i.AI_EXTRACTED_DATA:"gst_number"::STRING AS GST_NUMBER,
                   i.AI_EXTRACTED_DATA:"description"::STRING AS DESCRIPTION,
                   i.REJECTION_REASON,
                   c.EMAIL AS CONSULTANT_EMAIL,
                   d.DAYS_WORKED AS HR_DAYS
            FROM INVOICE_MGMT.PUBLIC.INVOICES i
            LEFT JOIN INVOICE_MGMT.PUBLIC.CONSULTANTS c ON i.CONSULTANT_ID = c.CONSULTANT_ID
            LEFT JOIN INVOICE_MGMT.PUBLIC.DAYS_WORKED d ON i.CONSULTANT_ID = d.CONSULTANT_ID AND i.INVOICE_MONTH = d.WORK_MONTH
            WHERE i.INVOICE_MONTH = '{sel_month_inv}'
            ORDER BY i.UPLOADED_AT DESC
        """).to_pandas()

        if len(invoices) == 0:
            st.info(f"No invoices found for {display_month_inv}.")
        else:
            # Summary metrics
            sm1, sm2, sm3, sm4 = st.columns(4)
            with sm1:
                st.metric("Total Invoices", len(invoices))
            with sm2:
                st.metric("Under Process", len(invoices[invoices["STATUS"] == "UNDER PROCESS"]))
            with sm3:
                st.metric("Verified", len(invoices[invoices["STATUS"] == "DETAILS VERIFIED"]))
            with sm4:
                st.metric("Paid", len(invoices[invoices["STATUS"] == "PAYMENT PROCESSED"]))

            # Bulk actions + Download ZIP
            with st.expander(":material/select_all: Bulk Actions", expanded=False):
                st.markdown("Apply a status change to **all** invoices for this month at once.")
                b1, b2 = st.columns([3, 1])
                with b1:
                    bulk_new_status = st.selectbox(
                        "Move all to",
                        ["DETAILS VERIFIED", "PAYMENT IN PROCESS", "PAYMENT PROCESSED", "REJECTED"],
                        key="bulk_new_status",
                    )
                bulk_reason = ""
                if bulk_new_status == "REJECTED":
                    bulk_reason = st.text_input("Rejection reason (required for rejection)", key="bulk_reason")

                with b2:
                    st.markdown("")
                    st.markdown("")
                    bulk_apply = st.button(":material/check_circle: Apply to All", type="primary", use_container_width=True, key="bulk_status_apply")

                if bulk_apply:
                    if bulk_new_status == "REJECTED" and not bulk_reason.strip():
                        st.error("Please provide a rejection reason.")
                    else:
                        inv_ids = ",".join([str(int(x)) for x in invoices["INVOICE_ID"].tolist()])
                        reason_sql = f", REJECTION_REASON = '{bulk_reason}'" if bulk_new_status == "REJECTED" else ""
                        payment_sql = f", PAYMENT_PROCESSED_BY = '{user['USERNAME']}', PAYMENT_PROCESSED_AT = {IST_SQL}" if bulk_new_status in ("PAYMENT IN PROCESS", "PAYMENT PROCESSED") else ""

                        session.sql(f"""
                            UPDATE INVOICE_MGMT.PUBLIC.INVOICES
                            SET STATUS = '{bulk_new_status}',
                                ACCOUNTING_VERIFIED_BY = '{user["USERNAME"]}',
                                ACCOUNTING_VERIFIED_AT = {IST_SQL}
                                {reason_sql}{payment_sql}
                            WHERE INVOICE_ID IN ({inv_ids})
                        """).collect()

                        if bulk_new_status == "REJECTED":
                            for _, inv_row in invoices.iterrows():
                                consultant_email = inv_row.get("CONSULTANT_EMAIL")
                                if consultant_email and str(consultant_email).strip() not in ("", "None", "null"):
                                    try:
                                        c_name = inv_row["FULL_NAME"] or "Consultant"
                                        c_inv_no = inv_row["INVOICE_NO"] or "N/A"
                                        session.sql(f"""
                                            CALL SYSTEM$SEND_EMAIL(
                                                'invoice_notifications',
                                                '{consultant_email}',
                                                'Invoice Rejected - Action Required',
                                                'Dear {c_name},\n\nYour invoice (#{c_inv_no}) for {display_month_inv} has been rejected.\n\nReason: {bulk_reason}\n\nPlease review and resubmit your invoice at your earliest convenience.\n\nRegards,\nAccounting Team'
                                            )
                                        """).collect()
                                    except Exception:
                                        pass

                        st.success(f"All {len(invoices)} invoices moved to **{bulk_new_status}**!")
                        st.rerun()

            # Download all as ZIP
            if st.button(":material/download: Download All Invoices (ZIP)", use_container_width=True, key="dl_all_inv"):
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for _, inv in invoices.iterrows():
                        try:
                            dl_dir = tempfile.mkdtemp()
                            session.file.get(f"@{STAGE_FQN}/{inv['FILE_NAME']}", dl_dir)
                            dl_path = os.path.join(dl_dir, inv["FILE_NAME"])
                            if os.path.exists(dl_path):
                                with open(dl_path, "rb") as f:
                                    zf.writestr(inv["FILE_NAME"], f.read())
                                os.unlink(dl_path)
                        except Exception:
                            pass
                zip_buffer.seek(0)
                st.download_button(
                    ":material/save: Save ZIP",
                    data=zip_buffer.getvalue(),
                    file_name=f"invoices_{sel_month_inv}.zip",
                    mime="application/zip",
                    key="zip_dl_inv",
                )

            st.divider()

            # Invoice cards with individual status update
            for _, inv in invoices.iterrows():
                badge_colors = {
                    "UNDER PROCESS": ("#FFF3E0", "#E65100"),
                    "DETAILS VERIFIED": ("#E3F2FD", "#1565C0"),
                    "PAYMENT IN PROCESS": ("#F3E5F5", "#6A1B9A"),
                    "PAYMENT PROCESSED": ("#E8F5E9", "#2E7D32"),
                    "REJECTED": ("#FFEBEE", "#C62828"),
                }
                bg, fg = badge_colors.get(inv["STATUS"], ("#F5F5F5", "#333"))

                with st.container(border=True):
                    h1, h2, h3 = st.columns([3, 2, 1])
                    with h1:
                        st.markdown(f"**{inv['FULL_NAME'] or inv['CONSULTANT_ID']}**")
                        st.caption(f"ID: {inv['CONSULTANT_ID']} | Invoice #: {inv['INVOICE_NO'] or '—'}")
                    with h2:
                        st.markdown(
                            f'<span style="background:{bg}; color:{fg}; padding:4px 14px; border-radius:16px; font-size:0.8rem; font-weight:600;">{inv["STATUS"]}</span>',
                            unsafe_allow_html=True,
                        )
                    with h3:
                        try:
                            dl_dir = tempfile.mkdtemp()
                            session.file.get(f"@{STAGE_FQN}/{inv['FILE_NAME']}", dl_dir)
                            dl_path = os.path.join(dl_dir, inv["FILE_NAME"])
                            if os.path.exists(dl_path):
                                with open(dl_path, "rb") as f:
                                    st.download_button(
                                        "PDF",
                                        data=f.read(),
                                        file_name=inv["FILE_NAME"],
                                        mime="application/pdf",
                                        key=f"dl_inv_{inv['INVOICE_ID']}",
                                        use_container_width=True,
                                    )
                                os.unlink(dl_path)
                        except Exception:
                            st.caption("—")

                    if inv["REJECTION_REASON"]:
                        st.error(f"Rejection Reason: {inv['REJECTION_REASON']}")

                    # Details row
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1:
                        st.caption("INVOICE DATE")
                        st.markdown(f"**{inv['INVOICE_DATE'] or '—'}**")
                    with c2:
                        st.caption("CONSULTANT DAYS")
                        wd = inv["WORKING_DAYS"]
                        st.markdown(f"**{int(wd) if wd and wd == wd else '—'}**")
                    with c3:
                        st.caption("HR DAYS")
                        hd = inv["HR_DAYS"]
                        st.markdown(f"**{int(hd) if hd and hd == hd else '—'}**")
                    with c4:
                        st.caption("DAYS MATCH")
                        wd_val = int(inv["WORKING_DAYS"]) if inv["WORKING_DAYS"] and inv["WORKING_DAYS"] == inv["WORKING_DAYS"] else None
                        hd_val = int(inv["HR_DAYS"]) if inv["HR_DAYS"] and inv["HR_DAYS"] == inv["HR_DAYS"] else None
                        if wd_val is not None and hd_val is not None:
                            if wd_val == hd_val:
                                st.markdown(":green[**Match**]")
                            else:
                                st.markdown(f":red[**Mismatch** ({hd_val} vs {wd_val})]")
                        else:
                            st.markdown("—")
                    with c5:
                        st.caption("AMOUNT")
                        st.markdown(f"**{inv['INVOICE_AMOUNT'] or '—'}**")

                    # Status update row
                    a1, a2, a3 = st.columns([2, 2, 1])
                    with a1:
                        new_st = st.selectbox(
                            "Move to",
                            ["DETAILS VERIFIED", "PAYMENT IN PROCESS", "PAYMENT PROCESSED", "REJECTED"],
                            key=f"st_{inv['INVOICE_ID']}",
                            label_visibility="collapsed",
                        )
                    with a2:
                        reason = ""
                        if new_st == "REJECTED":
                            reason = st.text_input("Reason", key=f"reason_{inv['INVOICE_ID']}", label_visibility="collapsed", placeholder="Rejection reason...")
                    with a3:
                        if st.button("Update", key=f"apply_st_{inv['INVOICE_ID']}", use_container_width=True):
                            if new_st == "REJECTED" and not reason.strip():
                                st.error("Provide a rejection reason.")
                            else:
                                reason_sql = f", REJECTION_REASON = '{reason}'" if new_st == "REJECTED" else ""
                                payment_sql = f", PAYMENT_PROCESSED_BY = '{user['USERNAME']}', PAYMENT_PROCESSED_AT = {IST_SQL}" if new_st in ("PAYMENT IN PROCESS", "PAYMENT PROCESSED") else ""

                                session.sql(f"""
                                    UPDATE INVOICE_MGMT.PUBLIC.INVOICES
                                    SET STATUS = '{new_st}',
                                        ACCOUNTING_VERIFIED_BY = '{user["USERNAME"]}',
                                        ACCOUNTING_VERIFIED_AT = {IST_SQL}
                                        {reason_sql}{payment_sql}
                                    WHERE INVOICE_ID = {int(inv['INVOICE_ID'])}
                                """).collect()

                                if new_st == "REJECTED":
                                    consultant_email = inv.get("CONSULTANT_EMAIL")
                                    if consultant_email and str(consultant_email).strip() not in ("", "None", "null"):
                                        try:
                                            c_name = inv["FULL_NAME"] or "Consultant"
                                            c_inv_no = inv["INVOICE_NO"] or "N/A"
                                            session.sql(f"""
                                                CALL SYSTEM$SEND_EMAIL(
                                                    'invoice_notifications',
                                                    '{consultant_email}',
                                                    'Invoice Rejected - Action Required',
                                                    'Dear {c_name},\n\nYour invoice (#{c_inv_no}) for {display_month_inv} has been rejected.\n\nReason: {reason}\n\nPlease review and resubmit your invoice at your earliest convenience.\n\nRegards,\nAccounting Team'
                                                )
                                            """).collect()
                                        except Exception:
                                            pass

                                st.rerun()

    # ─── REPORTS TAB ─────────────────────────────────────────────────────────
    with tab_reports:
        st.markdown("#### Monthly Reports & Analytics")
        sel_month_rpt, display_month_rpt = month_picker("rpt")

        report_summary = session.sql(f"""
            SELECT
                COUNT(DISTINCT CASE WHEN c.IS_ACTIVE = TRUE THEN c.CONSULTANT_ID END) AS TOTAL_ACTIVE_CONSULTANTS,
                COUNT(DISTINCT i.CONSULTANT_ID) AS CONSULTANTS_WITH_INVOICE,
                COUNT(i.INVOICE_ID) AS TOTAL_INVOICES,
                SUM(CASE WHEN i.STATUS = 'UNDER PROCESS' THEN 1 ELSE 0 END) AS PENDING_COUNT,
                SUM(CASE WHEN i.STATUS = 'DETAILS VERIFIED' THEN 1 ELSE 0 END) AS VERIFIED_COUNT,
                SUM(CASE WHEN i.STATUS = 'PAYMENT IN PROCESS' THEN 1 ELSE 0 END) AS PAYMENT_PROCESSING_COUNT,
                SUM(CASE WHEN i.STATUS = 'PAYMENT PROCESSED' THEN 1 ELSE 0 END) AS PAID_COUNT,
                SUM(CASE WHEN i.STATUS = 'REJECTED' THEN 1 ELSE 0 END) AS REJECTED_COUNT
            FROM INVOICE_MGMT.PUBLIC.CONSULTANTS c
            LEFT JOIN INVOICE_MGMT.PUBLIC.INVOICES i
                ON c.CONSULTANT_ID = i.CONSULTANT_ID AND i.INVOICE_MONTH = '{sel_month_rpt}'
        """).to_pandas()

        if len(report_summary) > 0:
            r = report_summary.iloc[0]

            # Overview broken up by status
            st.markdown(f"##### Status Overview — {display_month_rpt}")

            s1, s2, s3, s4, s5 = st.columns(5)
            with s1:
                st.markdown(f'<div class="metric-card"><h3 style="color:#E65100;">{int(r["PENDING_COUNT"])}</h3><p>UNDER PROCESS</p></div>', unsafe_allow_html=True)
            with s2:
                st.markdown(f'<div class="metric-card"><h3 style="color:#1565C0;">{int(r["VERIFIED_COUNT"])}</h3><p>DETAILS VERIFIED</p></div>', unsafe_allow_html=True)
            with s3:
                st.markdown(f'<div class="metric-card"><h3 style="color:#6A1B9A;">{int(r["PAYMENT_PROCESSING_COUNT"])}</h3><p>PAYMENT PROCESSING</p></div>', unsafe_allow_html=True)
            with s4:
                st.markdown(f'<div class="metric-card"><h3 style="color:#2E7D32;">{int(r["PAID_COUNT"])}</h3><p>PAYMENT DONE</p></div>', unsafe_allow_html=True)
            with s5:
                st.markdown(f'<div class="metric-card"><h3 style="color:#C62828;">{int(r["REJECTED_COUNT"])}</h3><p>REJECTED</p></div>', unsafe_allow_html=True)

            st.markdown("")
            k1, k2, k3 = st.columns(3)
            with k1:
                st.markdown(f'<div class="metric-card"><h3>{int(r["TOTAL_ACTIVE_CONSULTANTS"])}</h3><p>ACTIVE CONSULTANTS</p></div>', unsafe_allow_html=True)
            with k2:
                st.markdown(f'<div class="metric-card"><h3>{int(r["TOTAL_INVOICES"])}</h3><p>TOTAL SUBMITTED</p></div>', unsafe_allow_html=True)
            with k3:
                not_submitted = int(r["TOTAL_ACTIVE_CONSULTANTS"]) - int(r["CONSULTANTS_WITH_INVOICE"])
                st.markdown(f'<div class="metric-card"><h3>{not_submitted}</h3><p>NOT SUBMITTED</p></div>', unsafe_allow_html=True)

            st.markdown("")

            # Status breakdown chart
            st.markdown("##### Invoice Status Breakdown")
            status_data = pd.DataFrame({
                "Status": ["Under Process", "Details Verified", "Payment Processing", "Payment Done", "Rejected"],
                "Count": [
                    int(r["PENDING_COUNT"]),
                    int(r["VERIFIED_COUNT"]),
                    int(r["PAYMENT_PROCESSING_COUNT"]),
                    int(r["PAID_COUNT"]),
                    int(r["REJECTED_COUNT"]),
                ]
            })
            status_data = status_data[status_data["Count"] > 0]
            if len(status_data) > 0:
                st.bar_chart(status_data.set_index("Status"), horizontal=True)
            else:
                st.info("No invoice data to chart.")

            # ─── INVOICE DATA FOR VERIFICATION ────────────────────────────────
            st.divider()
            st.markdown("##### Invoice Data for Verification")
            st.caption("All AI-extracted fields from submitted invoices")

            invoice_details = session.sql(f"""
                SELECT i.CONSULTANT_ID, c.NAME AS FULL_NAME, i.STATUS,
                       i.AI_EXTRACTED_DATA:"invoice_no"::STRING AS INVOICE_NO,
                       i.AI_EXTRACTED_DATA:"name"::STRING AS NAME,
                       i.AI_EXTRACTED_DATA:"date"::STRING AS INVOICE_DATE,
                       i.AI_EXTRACTED_DATA:"description"::STRING AS DESCRIPTION,
                       i.AI_EXTRACTED_DATA:"days_worked"::STRING AS DAYS_WORKED_EXTRACTED,
                       i.AI_EXTRACTED_DATA:"total_days"::STRING AS TOTAL_DAYS,
                       i.AI_EXTRACTED_DATA:"amount"::STRING AS AMOUNT,
                       i.AI_EXTRACTED_DATA:"taxable_value"::STRING AS TAXABLE_VALUE,
                       i.AI_EXTRACTED_DATA:"tds_percent"::STRING AS TDS_PERCENT,
                       i.AI_EXTRACTED_DATA:"tds_amount"::STRING AS TDS_AMOUNT,
                       i.AI_EXTRACTED_DATA:"total"::STRING AS TOTAL,
                       i.AI_EXTRACTED_DATA:"grand_total"::STRING AS GRAND_TOTAL,
                       i.AI_EXTRACTED_DATA:"gst_number"::STRING AS GST_NUMBER,
                       i.AI_EXTRACTED_DATA:"pan_number"::STRING AS PAN_NUMBER,
                       i.AI_EXTRACTED_DATA:"hsn_code"::STRING AS HSN_CODE,
                       i.AI_EXTRACTED_DATA:"bank_name"::STRING AS BANK_NAME,
                       i.AI_EXTRACTED_DATA:"account_number"::STRING AS ACCOUNT_NUMBER,
                       i.AI_EXTRACTED_DATA:"ifsc_code"::STRING AS IFSC_CODE,
                       i.AI_EXTRACTED_DATA:"bill_to_name"::STRING AS BILL_TO_NAME,
                       i.AI_EXTRACTED_DATA:"bill_to_address"::STRING AS BILL_TO_ADDRESS,
                       i.AI_EXTRACTED_DATA:"employee_address"::STRING AS EMPLOYEE_ADDRESS,
                       i.AI_EXTRACTED_DATA:"is_signed"::STRING AS IS_SIGNED
                FROM INVOICE_MGMT.PUBLIC.INVOICES i
                LEFT JOIN INVOICE_MGMT.PUBLIC.CONSULTANTS c ON i.CONSULTANT_ID = c.CONSULTANT_ID
                WHERE i.INVOICE_MONTH = '{sel_month_rpt}'
                ORDER BY i.STATUS, c.NAME
            """).to_pandas()

            if len(invoice_details) == 0:
                st.info("No invoice data available for this month.")
            else:
                # Filter by status
                status_filter_rpt = st.multiselect(
                    "Filter by status",
                    invoice_details["STATUS"].dropna().unique().tolist(),
                    default=invoice_details["STATUS"].dropna().unique().tolist(),
                    key="rpt_status_filter",
                )
                filtered_details = invoice_details[invoice_details["STATUS"].isin(status_filter_rpt)] if status_filter_rpt else invoice_details

                st.dataframe(
                    filtered_details.rename(columns={
                        "CONSULTANT_ID": "ID",
                        "FULL_NAME": "Consultant",
                        "STATUS": "Status",
                        "INVOICE_NO": "Invoice #",
                        "NAME": "Name",
                        "INVOICE_DATE": "Date",
                        "DESCRIPTION": "Description",
                        "DAYS_WORKED_EXTRACTED": "Days (Extracted)",
                        "TOTAL_DAYS": "Total Days",
                        "AMOUNT": "Amount",
                        "TAXABLE_VALUE": "Taxable Value",
                        "TDS_PERCENT": "TDS %",
                        "TDS_AMOUNT": "TDS Amount",
                        "TOTAL": "Total",
                        "GRAND_TOTAL": "Grand Total",
                        "GST_NUMBER": "GST #",
                        "PAN_NUMBER": "PAN #",
                        "HSN_CODE": "HSN Code",
                        "BANK_NAME": "Bank",
                        "ACCOUNT_NUMBER": "Account #",
                        "IFSC_CODE": "IFSC",
                        "BILL_TO_NAME": "Bill To",
                        "BILL_TO_ADDRESS": "Bill Address",
                        "EMPLOYEE_ADDRESS": "Employee Address",
                        "IS_SIGNED": "Signed",
                    }),
                    use_container_width=True, hide_index=True,
                )

            # ─── DAYS WORKED COMPARISON ───────────────────────────────────────
            st.divider()
            st.markdown("##### Days Worked Comparison (HR vs Consultant)")

            days_report = session.sql(f"""
                SELECT c.CONSULTANT_ID, c.NAME AS FULL_NAME,
                       d.DAYS_WORKED AS HR_DAYS,
                       i.WORKING_DAYS AS CONSULTANT_DAYS,
                       i.AI_EXTRACTED_DATA:"grand_total"::STRING AS AMOUNT,
                       i.STATUS
                FROM INVOICE_MGMT.PUBLIC.CONSULTANTS c
                LEFT JOIN INVOICE_MGMT.PUBLIC.INVOICES i
                    ON c.CONSULTANT_ID = i.CONSULTANT_ID AND i.INVOICE_MONTH = '{sel_month_rpt}'
                LEFT JOIN INVOICE_MGMT.PUBLIC.DAYS_WORKED d
                    ON c.CONSULTANT_ID = d.CONSULTANT_ID AND d.WORK_MONTH = '{sel_month_rpt}'
                WHERE c.IS_ACTIVE = TRUE
                ORDER BY c.NAME
            """).to_pandas()

            if len(days_report) > 0:
                display_rpt = days_report.copy()
                display_rpt["HR DAYS"] = display_rpt["HR_DAYS"].apply(lambda x: int(x) if x and x == x else "—")
                display_rpt["CONSULTANT DAYS"] = display_rpt["CONSULTANT_DAYS"].apply(lambda x: int(x) if x and x == x else "—")
                display_rpt["MATCH"] = display_rpt.apply(
                    lambda row: "Yes" if row["HR_DAYS"] and row["CONSULTANT_DAYS"] and row["HR_DAYS"] == row["CONSULTANT_DAYS"]
                    else ("Mismatch" if row["HR_DAYS"] and row["CONSULTANT_DAYS"] and row["HR_DAYS"] != row["CONSULTANT_DAYS"]
                    else "—"), axis=1
                )
                st.dataframe(
                    display_rpt[["CONSULTANT_ID", "FULL_NAME", "HR DAYS", "CONSULTANT DAYS", "MATCH", "AMOUNT", "STATUS"]].rename(columns={
                        "CONSULTANT_ID": "ID", "FULL_NAME": "Name"
                    }),
                    use_container_width=True, hide_index=True,
                )

                mismatches = display_rpt[display_rpt["MATCH"] == "Mismatch"]
                if len(mismatches) > 0:
                    st.warning(f"{len(mismatches)} mismatch(es) found between HR and consultant days.")

# ─── MAIN FLOW ────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated"):
    show_login()
elif st.session_state.get("must_change_password"):
    show_change_password()
else:
    role = st.session_state.get("user_role")
    if role == "CONSULTANT":
        consultant_portal()
    elif role == "LEGAL_ADMIN":
        legal_admin_portal()
    elif role == "ACCOUNTING":
        accounting_portal()
    else:
        st.error("Unknown role. Please contact administrator.")