#!/usr/bin/env python3
from freshbooks import FreshBooksClient
import json

client = FreshBooksClient()

# Get all clients
print('Getting all clients to find Progress Software Corporation...')
result = client.get_clients()

# Parse response
if 'data' in result:
    data = json.loads(result['data'])
    clients = data.get('response', {}).get('result', {}).get('clients', [])
else:
    clients = result.get('response', {}).get('result', {}).get('clients', [])

# Find Progress Software Corporation
progress_client = None
for client_info in clients:
    org = client_info.get('organization', '').lower()
    if 'progress' in org and 'software' in org:
        progress_client = client_info
        break

if progress_client:
    print(f'Found client: {progress_client.get("organization", "N/A")}')
    print(f'Email: {progress_client.get("email", "N/A")}')
    print(f'First Name: {progress_client.get("fname", "N/A")}')
    print(f'Last Name: {progress_client.get("lname", "N/A")}')
    print(f'Client ID: {progress_client.get("id", "N/A")}')
    
    # Save client info
    with open('progress_client_info.json', 'w') as f:
        json.dump(progress_client, f, indent=2)
else:
    print('Progress Software Corporation client not found!')
    print('Available clients:')
    for client_info in clients[:10]:  # Show first 10
        print(f'- {client_info.get("organization", "N/A")} ({client_info.get("email", "N/A")})')