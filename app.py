import os
import requests
import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

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

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online", "hotels": [h['name'] for h in HOTELS]})

def _check_hotel_for_booking(hotel, conf_number):
    """Helper function to check a single hotel for a booking (used for parallel execution)."""
    if not hotel['api_key']:
        return None

    past = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
    future = (datetime.datetime.now() + datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    
    try:
        print(f"--- DEBUG: VERIFY BOOKING ---")
        print(f"Hotel: {hotel['name']}")
        print(f"Key (masked): {hotel['api_key'][:10]}...{hotel['api_key'][-4:]}")
        
        headers = {"x-api-key": hotel['api_key']}
        
        # 1. Direct search
        params_direct = {"reservationID": conf_number}
        resp_direct = requests.get(f"{CLOUDBEDS_API_URL}/getReservationsWithRateDetails", headers=headers, params=params_direct, timeout=10)
        
        if resp_direct.status_code == 200:
            data_direct = resp_direct.json()
            if data_direct.get('success') and data_direct.get('data'):
                res = data_direct['data'][0]
                if res.get('status') == 'confirmed':
                    return {
                        "success": True,
                        "hotel": hotel['name'],
                        "propertyID": res.get('propertyID'),
                        "reservationID": res.get('reservationID'),
                        "guestID": res.get('guestID'),
                        "guestName": res.get('guestName'),
                        "checkIn": res.get('reservationCheckIn'),
                        "checkOut": res.get('reservationCheckOut'),
                        "status": res.get('status')
                    }

        # 2. Broad search
        params_list = {"status": "confirmed", "checkInFrom": past, "checkInTo": future}
        resp_list = requests.get(f"{CLOUDBEDS_API_URL}/getReservationsWithRateDetails", headers=headers, params=params_list, timeout=10)
        
        if resp_list.status_code == 200:
            data_list = resp_list.json()
            if data_list.get('success'):
                for res in data_list.get('data', []):
                    if conf_number in [str(res.get('reservationID', '')), str(res.get('sourceReservationID', ''))]:
                        return {
                            "success": True,
                            "hotel": hotel['name'],
                            "propertyID": res.get('propertyID'),
                            "reservationID": res.get('reservationID'),
                            "guestID": res.get('guestID'),
                            "guestName": res.get('guestName'),
                            "checkIn": res.get('reservationCheckIn'),
                            "checkOut": res.get('reservationCheckOut'),
                            "status": res.get('status')
                        }
    except requests.exceptions.Timeout:
        print(f"--- TIMEOUT: {hotel['name']} (skipped) ---")
    except Exception as e:
        print(f"--- ERROR: {hotel['name']} -> {str(e)} ---")
    
    return None

@app.route('/api/verify-booking', methods=['POST'])
def verify_booking():
    data = request.json
    conf_number = str(data.get('confirmationNumber', '')).strip()
    
    if not conf_number:
        return jsonify({"success": False, "message": "Confirmation number is required"}), 400

    # Run searches for all hotels in parallel
    with ThreadPoolExecutor(max_workers=len(HOTELS)) as executor:
        future_to_hotel = {executor.submit(_check_hotel_for_booking, hotel, conf_number): hotel for hotel in HOTELS}
        
        for future in as_completed(future_to_hotel):
            result = future.result()
            if result:
                print(f"--- SUCCESS: Found in {result['hotel']} ---")
                return jsonify(result)

    print("--- FAILED: No booking found in any hotel ---")
    return jsonify({"success": False, "message": "No confirmed booking found for this ID across any hotel."}), 404

@app.route('/api/upload-photo', methods=['POST'])
def upload_photo():
    print("--- UPLOAD PHOTO ROUTE HIT ---")
    print(f"Form data: {request.form}")
    guest_id = request.form.get('guestID')
    hotel_name = request.form.get('hotelName')
    image_file = request.files.get('image')

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel: return jsonify({"success": False, "message": "Invalid hotel"}), 400

    if not image_file: return jsonify({"success": False, "message": "No image file provided"}), 400

    try:
        print(f"--- DEBUG: UPLOAD PHOTO ---")
        print(f"Hotel: {hotel['name']}")
        print(f"Key (masked): {hotel['api_key'][:10]}...{hotel['api_key'][-4:]}")
        
        url = f"{CLOUDBEDS_API_URL}/postGuestPhoto"
        headers = {"accept": "application/json", "x-api-key": hotel['api_key']}
        # Cloudbeds postGuestPhoto often uses 'file' key even for photos
        files = {'file': (image_file.filename, image_file.read(), image_file.content_type)}
        data = {"guestID": guest_id}
        
        response = requests.post(url, headers=headers, data=data, files=files)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/upload-document', methods=['POST'])
def upload_document():
    print("--- UPLOAD DOCUMENT ROUTE HIT ---")
    guest_id = request.form.get('guestID')
    hotel_name = request.form.get('hotelName')
    image_file = request.files.get('image')

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel:
        print(f"--- FAILED: UPLOAD DOCUMENT ---")
        print(f"Error: Hotel '{hotel_name}' not found in HOTELS list.")
        return jsonify({"success": False, "message": "Invalid hotel"}), 400

    if not image_file: return jsonify({"success": False, "message": "No document file provided"}), 400

    try:
        print(f"--- DEBUG: UPLOAD DOCUMENT ---")
        print(f"Hotel: {hotel['name']}")
        print(f"Key (masked): {hotel['api_key'][:10]}...{hotel['api_key'][-4:]}")
        
        url = f"{CLOUDBEDS_API_URL}/postGuestDocument"
        headers = {"accept": "application/json", "x-api-key": hotel['api_key']}
        files = {'file': (image_file.filename, image_file.read(), image_file.content_type)}
        data = {"guestID": guest_id}
        
        response = requests.post(url, headers=headers, data=data, files=files)
        print(f"--- CLOUDBEDS RESPONSE (DOC) ---")
        print(f"Status: {response.status_code}")
        print(f"Body: {response.text}")
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/complete-checkin', methods=['POST'])
def complete_checkin():
    data = request.json
    reservation_id = data.get('reservationID')
    hotel_name = data.get('hotelName')

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel: return jsonify({"success": False, "message": "Invalid hotel"}), 400

    try:
        print(f"--- DEBUG: COMPLETE CHECKIN ---")
        print(f"Hotel: {hotel['name']}")
        print(f"Key (masked): {hotel['api_key'][:10]}...{hotel['api_key'][-4:]}")

        url = f"{CLOUDBEDS_API_URL}/putReservation"
        headers = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded", "x-api-key": hotel['api_key']}
        payload = {"reservationID": str(reservation_id), "status": "checked_in"}
        
        response = requests.put(url, headers=headers, data=payload)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/hotel-details', methods=['GET'])
def get_hotel_details():
    property_id = request.args.get('propertyID')
    hotel_name = request.args.get('hotelName')

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel: return jsonify({"success": False, "message": "Invalid hotel"}), 400

    try:
        url = f"{CLOUDBEDS_API_URL}/getHotelDetails"
        headers = {"accept": "application/json", "x-api-key": hotel['api_key']}
        params = {"propertyID": property_id}
        
        response = requests.get(url, headers=headers, params=params)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)
