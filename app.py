import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

app = Flask(__name__)
CORS(app)

# Configuration: Load multi-hotel API keys from a comma-separated list in .env
keys_str = os.getenv("CLOUDBEDS_API_KEYS", "")
api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]

# Build HOTELS list dynamically
HOTELS = []
for i, key in enumerate(api_keys):
    HOTELS.append({"name": f"Hotel {i+1}", "api_key": key})

print(f"--- SERVER START: {len(HOTELS)} Active Hotels ---")
for h in HOTELS:
    print(f"Loaded: {h['name']} ({h['api_key'][:10]}...)")

CLOUDBEDS_API_URL = "https://api.cloudbeds.com/api/v1.3"

@app.route('/api/verify-booking', methods=['POST'])
def verify_booking():
    data = request.json
    first_name = data.get('firstName', '').lower().strip()
    last_name = data.get('lastName', '').lower().strip()
    start_date = data.get('startDate') # YYYY-MM-DD
    end_date = data.get('endDate')     # YYYY-MM-DD

    if not (first_name and last_name and start_date and end_date):
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    for hotel in HOTELS:
        if not hotel['api_key']:
            continue
            
        try:
            print(f"Checking {hotel['name']}...")
            headers = {"x-api-key": hotel['api_key']}
            # Use date filters to avoid the 100-result limit and improve performance
            params = {
                "checkInFrom": start_date,
                "checkInTo": start_date
            }
            response = requests.get(f"{CLOUDBEDS_API_URL}/getReservations", headers=headers, params=params)
            
            if response.status_code == 200:
                res_data = response.json()
                print(f"Found {len(res_data.get('data', []))} reservations in {hotel['name']}")
                if res_data.get('success'):
                    for res in res_data.get('data', []):
                        guest_name = res.get('guestName', '').lower()
                        # Check if both names are in the guestName string
                        if first_name in guest_name and last_name in guest_name:
                            # Verify dates match
                            if res.get('startDate') == start_date and res.get('endDate') == end_date:
                                # Found a match! We return it regardless of status to be flexible
                                print(f"Match found in {hotel['name']}: {res.get('guestName')} (Status: {res.get('status')})")
                                return jsonify({
                                    "success": True,
                                    "hotel": hotel['name'],
                                    "propertyID": res.get('propertyID'),
                                    "reservationID": res.get('reservationID'),
                                    "guestID": res.get('guestID'),
                                    "status": res.get('status')
                                })
            else:
                # Pass through the exact Cloudbeds error if one occurs
                try:
                    err_data = response.json()
                    print(f"Cloudbeds API Error ({hotel['name']}): {err_data.get('message')}")
                    if not err_data.get('success'):
                        return jsonify(err_data), response.status_code
                except:
                    pass
        except Exception as e:
            pass

    return jsonify({"success": False, "message": "No matching booking found in any hotel."}), 404

@app.route('/api/upload-photo', methods=['POST'])
def upload_photo():
    guest_id = request.form.get('guestID')
    hotel_name = request.form.get('hotelName')
    image_file = request.files.get('image')

    if not (guest_id and hotel_name and image_file):
        return jsonify({"success": False, "message": "Missing guestID, hotelName, or image"}), 400

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel or not hotel['api_key']:
        return jsonify({"success": False, "message": "Invalid hotel"}), 400

    try:
        url = f"{CLOUDBEDS_API_URL}/postGuestPhoto"
        headers = {"x-api-key": hotel['api_key']}
        files = {'image': (image_file.filename, image_file.read(), image_file.content_type)}
        params = {"guestID": guest_id}
        
        response = requests.post(url, headers=headers, params=params, files=files)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/upload-document', methods=['POST'])
def upload_document():
    guest_id = request.form.get('guestID')
    hotel_name = request.form.get('hotelName')
    image_file = request.files.get('image')

    if not (guest_id and hotel_name and image_file):
        return jsonify({"success": False, "message": "Missing guestID, hotelName, or image"}), 400

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel or not hotel['api_key']:
        return jsonify({"success": False, "message": "Invalid hotel"}), 400

    try:
        url = f"{CLOUDBEDS_API_URL}/postGuestDocument"
        headers = {"x-api-key": hotel['api_key']}
        files = {'image': (image_file.filename, image_file.read(), image_file.content_type)}
        params = {"guestID": guest_id, "type": "Passport"}
        
        response = requests.post(url, headers=headers, params=params, files=files)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/complete-checkin', methods=['POST'])
def complete_checkin():
    data = request.json
    reservation_id = data.get('reservationID')
    property_id = data.get('propertyID')
    hotel_name = data.get('hotelName')

    if not (reservation_id and hotel_name):
        return jsonify({"success": False, "message": "Missing reservationID or hotelName"}), 400

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel or not hotel['api_key']:
        return jsonify({"success": False, "message": "Invalid hotel"}), 400

    try:
        url = f"{CLOUDBEDS_API_URL}/putReservation"
        headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "x-api-key": hotel['api_key']
        }
        payload = {
            "reservationID": str(reservation_id),
            "status": "checked_in"
        }
        
        response = requests.put(url, headers=headers, data=payload)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
