#!/usr/bin/env python3
"""
Test script for the active service API endpoint
"""
import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Django settings
INTERNAL_API_KEY = os.getenv('INTERNAL_API_KEY', 'test-key-123')
BASE_URL = 'http://localhost:8000'

def test_active_service_api():
    """Test the active service API endpoint"""

    # Test data - using the real phone number from the database
    test_phone = "18765952596"  # Real phone number from database

    # API endpoint URL
    url = f"{BASE_URL}/api/phone/active-service/"

    # Headers
    headers = {
        'Authorization': f'Bearer {INTERNAL_API_KEY}',
        'Content-Type': 'application/json'
    }

    # Request payload
    payload = {
        'phone': test_phone
    }

    print(f"Testing active service API with phone: {test_phone}")
    print(f"URL: {url}")
    print(f"Headers: {headers}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        # Make the request
        response = requests.post(url, headers=headers, json=payload)

        print(f"\nResponse Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Body: {response.text}")

        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ API call successful!")
            print(f"Active service: {data.get('active_service')}")
        else:
            print(f"\n❌ API call failed!")
            if response.status_code == 401:
                print("Error: Unauthorized - check your INTERNAL_API_KEY")
            elif response.status_code == 404:
                print("Error: No user found with this phone number")
            else:
                print(f"Error: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ Connection failed! Make sure the Django server is running on port 8000")
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    test_active_service_api()
