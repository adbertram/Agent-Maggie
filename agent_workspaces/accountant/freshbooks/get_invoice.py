#!/usr/bin/env python3

from freshbooks import FreshBooksClient

def get_invoice_details():
    client = FreshBooksClient()
    
    # Get invoice 00000835
    invoice = client.get_invoice('00000835')
    invoice_data = invoice['response']['result']['invoice']
    
    print('Current invoice details:')
    print(f'Invoice ID: {invoice_data["id"]}')
    print(f'Invoice Number: {invoice_data["invoice_number"]}')
    print(f'Client: {invoice_data["fname"]} {invoice_data["lname"]}')
    print(f'Email: {invoice_data["email"]}')
    print(f'Organization: {invoice_data.get("organization", "N/A")}')
    print(f'Total: ${invoice_data["amount"]["amount"]} {invoice_data["amount"]["code"]}')
    print(f'Status: {invoice_data["v3_status"]}')
    print()
    print('Line items:')
    for item in invoice_data['lines']:
        print(f'- {item["name"]}: ${item["unit_cost"]["amount"]} (qty: {item["qty"]})')
    
    return invoice_data

if __name__ == '__main__':
    get_invoice_details()