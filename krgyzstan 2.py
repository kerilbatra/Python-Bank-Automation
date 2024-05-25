import pdfplumber
from googletrans import Translator
import numpy as np
import pandas as pd
import re
import parse
from collections import namedtuple
import streamlit as st
import base64
from io import BytesIO
from datetime import datetime


# Function to translate a text from Russian to English
def translate_to_english(text):
    translator = Translator()
    translation = translator.translate(text, dest='en')
    return translation.text


# Create a function to allow downloading the processed Excel file
def download_processed_file(dataframe):
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    dataframe.to_excel(writer, index=False, header=True)
    writer.close()
    processed_data = output.getvalue()
    b64 = base64.b64encode(processed_data).decode()
    href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="Bank Entries.xlsx">Download Processed Transaction Entries</a>'
    st.markdown(href, unsafe_allow_html=True)



def Asia_all_bank(pdf_path, entity_mapping, mapping_gl):

    master_df = pd.DataFrame()

    with pdfplumber.open(pdf_path) as pdf:
        for page_number in range(len(pdf.pages)):
            tables = pdf.pages[page_number].extract_tables()
            
            for idx, table in enumerate(tables):
                df = pd.DataFrame(table)
                master_df = pd.concat([master_df, df], ignore_index=True)

    # Promote the first row as the header
    master_df.columns = master_df.iloc[0]
    # Drop the first row (now that it's the header)
    master_df = master_df[2:]

    master_df = master_df[master_df['Документ'] != 'Документ']
    master_df = master_df[~(master_df['Корреспондент'].isna())]
    master_df = master_df.reset_index(drop=True)

    # List of columns to drop
    columns_to_drop = ['Документ', 'Назначение платежа']
    master_df = master_df.drop(columns=columns_to_drop)
    # Extract the first set of consecutive digits after "ИНН: "
    master_df['ИНН'] = master_df['Корреспондент'].str.extract(r'ИНН\s*(\d+)')

    #removing \n
    master_df['Оборот\nДт'] = master_df['Оборот\nДт'].str.replace("\n","")
    master_df['Оборот\nКт'] = master_df['Оборот\nКт'].str.replace("\n","")

    #removing ,
    master_df['Оборот\nДт'] = master_df['Оборот\nДт'].str.replace(",","")
    master_df['Оборот\nКт'] = master_df['Оборот\nКт'].str.replace(",","")

    # Specify the column names
    debit_column = 'Оборот\nДт'
    credit_column = 'Оборот\nКт'

    # Create a new column 'Transaction_Type'
    master_df['Transaction_Type'] = np.where(
            (master_df[debit_column] != '0.00') & (master_df[credit_column] == '0.00'),
            'Debit_Transaction',
            'Credit_Transaction')

    # Creating a column called transaction amount
    master_df['Transaction_Amount'] = np.where(
            (master_df['Transaction_Type'] == 'Debit_Transaction'),
            master_df[debit_column],
            master_df[credit_column])

    master_df['Posted_Amount'] = master_df['Transaction_Amount']
    master_df['Transaction_Currency'] = 'KGS'
    master_df['Posted_Cuurency'] = 'KGS'
    master_df['Account_Currency'] = 'KGS'
    master_df['Account_Number'] = '1030120000002658'
    master_df['Account_Title'] = 'HERBION KYRGYZSTAN'
    master_df['Posting_Rate'] = ''

    # Specify the new column names
    new_column_names = {'Дата\nоперации': 'posting_dates',
                        'Transaction_Type': 'labels',
                        'Transaction_Entity': 'transaction_entity',
                        'ИНН': 'transaction_entity'}

    # Rename the columns
    master_df.rename(columns=new_column_names, inplace=True)

    master_df['Оборот\nДт'] = master_df['Оборот\nДт'].str.replace("\n","")
    master_df['Оборот\nКт'] = master_df['Оборот\nКт'].str.replace("\n","")
    master_df['Оборот\nДт'] = master_df['Оборот\nДт'].str.replace(",","")
    master_df['Оборот\nКт'] = master_df['Оборот\nКт'].str.replace(",","")

    #removing \n

    result_df = pd.DataFrame()
    #Edit idher karna
    master_df['transaction_entity'].fillna(0, inplace=True)
    master_df['transaction_entity'] = master_df['transaction_entity'].astype('int64')
    master_df['transaction_entity'] = master_df['transaction_entity'].astype('str')
    
    result_df = pd.merge(master_df, entity_mapping, left_on='transaction_entity', right_on='INN', how='left')
    result_df['Entity'] = result_df['Entity'].astype('str')
    result_df['Entity'] = result_df['Entity'].str.replace(".0", "")
    # Filter out rows with blank, null, or 0 entity code
    missing_mapping_df = result_df[result_df['INN'].isna()]
    
    if len(missing_mapping_df['transaction_entity']) == 0:

        # Drop the duplicate column introduced by the merge
        result_df = result_df.drop(columns=['Posting_Rate','INN'])

        result_df['Transaction_Type'] = np.where(result_df['labels'] == 'Debit_Transaction', 'KZ', 'DZ')
        result_df['Posting Key D/K'] = np.where(result_df['Transaction_Type'] == 'DZ','15','25')
        result_df['Posting Key GL'] = np.where(result_df['Transaction_Type'] == 'DZ','40','50')
        result_df['Reference'] = np.where(result_df['Transaction_Type'] == 'DZ','Inflow','Outflow')

        # Perform left join
        result_df = pd.merge(result_df, mapping_gl, left_on='Account_Number', right_on='account_number', how='left')
        result_df['G/L Account_1'] = np.where(result_df['Reference'] == 'Inflow', result_df['G/L Account'] + 1, result_df['G/L Account'] + 2)
        result_df.drop(columns=['Account_Number','account_number', 'G/L Account'], inplace=True)

        # Adding Required columns
        result_df['Document Date'] = result_df['posting_dates']
        result_df['Period'] = pd.to_datetime(result_df['Document Date'], format='%d.%m.%Y').dt.strftime('%m')
        result_df['Baseline Date'] = result_df['posting_dates']
        result_df['GL Amount'] = result_df['Posted_Amount']
        result_df['Value Date'] = result_df['posting_dates']

        result_df['Cost Center'] = ''

        # Renaming columns
        result_df = result_df.rename(columns={
                'Document Date': 'Document Date',
                'Transaction_Type': 'Document Type',
                'Company Code': 'Company Code',
                'posting_dates': 'Posting Date',
                'Period': 'Posting Period',
                'Posted_Cuurency': 'Currency',
                'Reference': 'Reference',
                'Posting Key D/K':'Posting Key D/K',
                'Entity':'Account D/K',
                'Posted_Amount':'Amount D/K',
                'Baseline Date':'Baseline Date',
                'Posting Key GL':'Posting Key GL',
                'G/L Account_1':'Account GL',
                'GL Amount': 'Amount GL',
                'Value Date': 'Value Date',
                'Cost Center':'Profit Center'})

        column_order = ['Document Date', 'Document Type', 'Company Code', 'Posting Date', 'Posting Period', 'Currency',
                        'Reference', 'Posting Key D/K', 'Account D/K', 'Amount D/K', 'Baseline Date', 'Posting Key GL',
                        'Account GL', 'Amount GL', 'Value Date', 'Profit Center']

        # Set the column order
        result_df = result_df[column_order]
        entity_mapping_2 = entity_mapping[['Entity','Category']]
        entity_mapping_2['Entity'] = entity_mapping_2['Entity'].astype(str)

        result_df = pd.merge(result_df, entity_mapping_2, left_on = 'Account D/K', right_on = 'Entity', how='left')

        # Conditions for transformation
        condition1 = (result_df['Document Type'] == 'DZ') & (result_df['Category'] == 'Vendor')
        condition2 = (result_df['Document Type'] == 'KZ') & (result_df['Category'] == 'Customer')

        # Update values based on conditions
        result_df.loc[condition1, 'Document Type'] = 'KA'
        result_df.loc[condition1, 'Posting Key D/K'] = 35

        result_df.loc[condition2, 'Document Type'] = 'DA'
        result_df.loc[condition2, 'Posting Key D/K'] = 5

        # Convert columns to specified data types
        result_df['Posting Period'] = result_df['Posting Period'].astype(int)
        result_df['Posting Key D/K'] = result_df['Posting Key D/K'].astype(int)
        result_df['Amount D/K'] = result_df['Amount D/K'].astype(float)
        result_df['Posting Key GL'] = result_df['Posting Key GL'].astype(int)
        result_df['Amount GL'] = result_df['Amount GL'].astype(float)
        result_df = result_df.drop(columns = ['Entity','Category'])
        reverse_entries = result_df[(result_df['Document Type'] == 'KA') | (result_df['Document Type'] == 'DA')]
        result_df = result_df[~((result_df['Document Type'] == 'KA') | (result_df['Document Type'] == 'DA'))]
        if len(reverse_entries['Document Type']) == 0:
            reverser_entries = pd.DataFrame(columns = column_order)

        return (result_df, reverse_entries)
    else:
        print ("Mapping Missing for Following INN Codes:")
        print (missing_mapping_df['transaction_entity'])
        print ('Update Missing for Above Mentioned Entities and Try Again')
        return (missing_mapping_df)


# GL Mapping
mapping_gl = pd.read_excel(r"Give your GL Mapping Here")
mapping_gl['account_number'] = mapping_gl['Description (LONG)'].str.split('|').str[1].str.strip()
mapping_gl = mapping_gl[['G/L Account','Company Code','account_number']]

vendor_mapping = pd.read_excel(r"Give your vendor Mapping Here")
vendor_mapping['INN'] = vendor_mapping["INN"].astype(str)
vendor_mapping['INN'] = vendor_mapping["INN"].str.replace(".0",'')
vendor_mapping['Category'] = 'Vendor'
vendor_mapping.rename(columns={'Vendor': 'Entity'}, inplace=True)
customer_mapping = pd.read_excel(r"Give your customer Mapping Here")
customer_mapping['INN'] = customer_mapping['INN'].astype(str)
customer_mapping['INN'] = customer_mapping['INN'].str.replace(".0",'')
customer_mapping['Category'] = 'Customer'
customer_mapping.rename(columns={'Customer': 'Entity'}, inplace=True)

# Appending two dataframes to create one dataframe
entity_mapping = pd.DataFrame()
entity_mapping = pd.concat([customer_mapping,vendor_mapping], ignore_index= True)
entity_mapping = entity_mapping[['Entity','INN','Category']]



# Set the Streamlit page configuration
st.set_page_config(layout="wide")

# Path to your image file
image_path = r"Give an Image Path Here"
# Set the desired width and height
width = 400
height = 200


# Use HTML and CSS to position and size the image
st.markdown(
    f"""
    <div style="position: absolute; top: 0; right: 0;">
        <img src="data:image/png;base64,{base64.b64encode(open(image_path, 'rb').read()).decode()}" alt="Your Image" width="{width}" height="{height}">
    </div>
    """,
    unsafe_allow_html=True
)

st.title("Bank Name Statements Automation")


normal_transaction = []
b2b = []
reversals = []
# File uploader
st.markdown("### ***Enter Your Bank Name***")
uploaded_file_1 = st.file_uploader("Upload Bank Statement for Account in USD", type=["pdf"])
if uploaded_file_1 is not None:
    result_df_aab = Asia_all_bank(uploaded_file_1, entity_mapping, mapping_gl)
 
    if isinstance(result_df_aab, pd.DataFrame):
        st.write("Missing Mappings: Update The Mapping Sheet to Continue")
        result_df_aab
    else:
        st.write("Statement is Processed")
        normal_entries_aab, reverse_entries_aab = result_df_aab
        normal_transaction.append(normal_entries_aab)
        reversals.append(reverse_entries_aab)
        #b2b.append(bank_2_bank_entries)

# Concatenate all the dataframes
if len(normal_transaction) > 0:
    normal_transactions_final = pd.concat(normal_transaction, ignore_index=True)
    if len(normal_transactions_final['Document Type']) > 0:    
        st.markdown("## Bank Entries for SAP")

        
    st.markdown("**_Download Processed Plan for Uploading in SAP_**")
    # Add the download button
    download_processed_file(normal_transactions_final)


if len(reversals) > 0:
    reversals_final = pd.concat(reversals, ignore_index=True)
    if len(reversals_final['Document Type']) > 0:
        st.markdown("## Reversal Bank Entries")

    st.markdown("**_Download Reversal Entries for Manual Uploading in SAP_**")
    # Add the download button
    download_processed_file(reversals_final)

if len(b2b) > 0:
    b2b_final = pd.concat(b2b, ignore_index=True)
    if len(b2b_final['labels']) > 0:
        st.markdown("## Bank to Bank Transfers")

    st.markdown("**_Download Bank to Bank Transfer Entries for Manual Uploading in SAP_**")
    # Add the download button
    download_processed_file(b2b_final)


