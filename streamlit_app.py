# Streamlit Invoice Management App configured for VS Code with Snowflake connection
# Co-authored with CoCo
import streamlit as st
from snowflake.snowpark.context import get_active_session
from snowflake.snowpark import Session
import os


def get_snowflake_session():
    """
    Get Snowflake session - works both in Snowsight and locally in VS Code.
    In Snowsight: uses get_active_session()
    In VS Code: uses connection.toml or environment variables
    """
    try:
        # Try Snowsight session first
        return get_active_session()
    except Exception:
        # Fall back to local connection for VS Code
        connection_parameters = {
            "account": os.getenv("SNOWFLAKE_ACCOUNT", "<your_account>"),
            "user": os.getenv("SNOWFLAKE_USER", "<your_user>"),
            "password": os.getenv("SNOWFLAKE_PASSWORD", "<your_password>"),
            "role": os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
            "database": os.getenv("SNOWFLAKE_DATABASE", "INVOICE_MGMT"),
            "schema": os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
        }
        return Session.builder.configs(connection_parameters).create()


session = get_snowflake_session()

st.set_page_config(page_title="Invoice Management", page_icon="🧾", layout="wide")
st.title("🧾 Invoice Management System")

# --- Sidebar ---
st.sidebar.header("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Create Invoice", "Manage Invoices"])

# --- Helper Functions ---


def init_tables():
    """Create tables if they don't exist."""
    session.sql("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id NUMBER AUTOINCREMENT,
            customer_name VARCHAR,
            invoice_date DATE,
            due_date DATE,
            amount FLOAT,
            status VARCHAR DEFAULT 'Pending',
            description VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
        )
    """).collect()


def get_invoices():
    """Fetch all invoices."""
    return session.sql("SELECT * FROM invoices ORDER BY invoice_id DESC").to_pandas()


def create_invoice(customer_name, invoice_date, due_date, amount, description):
    """Insert a new invoice."""
    session.sql(f"""
        INSERT INTO invoices (customer_name, invoice_date, due_date, amount, description)
        VALUES ('{customer_name}', '{invoice_date}', '{due_date}', {amount}, '{description}')
    """).collect()


def update_status(invoice_id, new_status):
    """Update invoice status."""
    session.sql(f"""
        UPDATE invoices SET status = '{new_status}' WHERE invoice_id = {invoice_id}
    """).collect()


def delete_invoice(invoice_id):
    """Delete an invoice."""
    session.sql(f"DELETE FROM invoices WHERE invoice_id = {invoice_id}").collect()


# Initialize tables
init_tables()

# --- Pages ---
if page == "Dashboard":
    st.header("📊 Dashboard")

    invoices_df = get_invoices()

    if invoices_df.empty:
        st.info("No invoices yet. Create one from the sidebar!")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Invoices", len(invoices_df))
        with col2:
            st.metric("Total Amount", f"${invoices_df['AMOUNT'].sum():,.2f}")
        with col3:
            pending = len(invoices_df[invoices_df['STATUS'] == 'Pending'])
            st.metric("Pending", pending)
        with col4:
            paid = len(invoices_df[invoices_df['STATUS'] == 'Paid'])
            st.metric("Paid", paid)

        st.subheader("Recent Invoices")
        st.dataframe(invoices_df, use_container_width=True)

elif page == "Create Invoice":
    st.header("➕ Create New Invoice")

    with st.form("invoice_form"):
        customer_name = st.text_input("Customer Name")
        col1, col2 = st.columns(2)
        with col1:
            invoice_date = st.date_input("Invoice Date")
        with col2:
            due_date = st.date_input("Due Date")
        amount = st.number_input("Amount ($)", min_value=0.0, step=0.01)
        description = st.text_area("Description")
        submitted = st.form_submit_button("Create Invoice")

        if submitted:
            if customer_name and amount > 0:
                create_invoice(customer_name, invoice_date, due_date, amount, description)
                st.success(f"Invoice created for {customer_name}!")
                st.rerun()
            else:
                st.error("Please fill in customer name and amount.")

elif page == "Manage Invoices":
    st.header("📝 Manage Invoices")

    invoices_df = get_invoices()

    if invoices_df.empty:
        st.info("No invoices to manage.")
    else:
        for _, row in invoices_df.iterrows():
            with st.expander(f"Invoice #{int(row['INVOICE_ID'])} - {row['CUSTOMER_NAME']}"):
                st.write(f"**Amount:** ${row['AMOUNT']:,.2f}")
                st.write(f"**Status:** {row['STATUS']}")
                st.write(f"**Due Date:** {row['DUE_DATE']}")
                st.write(f"**Description:** {row['DESCRIPTION']}")

                col1, col2 = st.columns(2)
                with col1:
                    new_status = st.selectbox(
                        "Update Status",
                        ["Pending", "Paid", "Overdue", "Cancelled"],
                        key=f"status_{row['INVOICE_ID']}"
                    )
                    if st.button("Update", key=f"update_{row['INVOICE_ID']}"):
                        update_status(row['INVOICE_ID'], new_status)
                        st.success("Status updated!")
                        st.rerun()
                with col2:
                    if st.button("🗑️ Delete", key=f"delete_{row['INVOICE_ID']}"):
                        delete_invoice(row['INVOICE_ID'])
                        st.warning("Invoice deleted.")
                        st.rerun()
