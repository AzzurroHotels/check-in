import os
import requests
import datetime
from flask import Flask, request, jsonify, send_file
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

@app.route('/')
def serve_index():
    return send_file('index.html')

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online", "hotels": [h['name'] for h in HOTELS]})

def _check_hotel_for_booking(hotel, conf_number):
    """Helper function to check a single hotel using multiple parallel strategies."""
    if not hotel['api_key']: return None
    
    headers = {"x-api-key": hotel['api_key']}
    
    # Define search tasks
    def search_by_id(param_name):
        try:
            params = {param_name: conf_number}
            resp = requests.get(f"{CLOUDBEDS_API_URL}/getReservationsWithRateDetails", 
                                headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success') and data.get('data'):
                    res = data['data'][0]
                    if res.get('status') == 'confirmed':
                        return _format_res(res, hotel['name'])
        except: pass
        return None

    def search_broad():
        try:
            # Narrower window: -7 to +60 days for better performance
            past = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
            future = (datetime.datetime.now() + datetime.timedelta(days=60)).strftime('%Y-%m-%d')
            params = {"status": "confirmed", "checkInFrom": past, "checkInTo": future}
            resp = requests.get(f"{CLOUDBEDS_API_URL}/getReservationsWithRateDetails", 
                                headers=headers, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    for res in data.get('data', []):
                        if conf_number in [str(res.get('reservationID', '')), str(res.get('sourceReservationID', ''))]:
                            return _format_res(res, hotel['name'])
        except: pass
        return None

    # Run sub-tasks in parallel for THIS hotel
    with ThreadPoolExecutor(max_workers=3) as sub_executor:
        futures = [
            sub_executor.submit(search_by_id, "reservationID"),
            sub_executor.submit(search_by_id, "sourceReservationID"),
            sub_executor.submit(search_broad)
        ]
        for f in as_completed(futures):
            res = f.result()
            if res: return res
    return None

def _format_res(res, hotel_name):
    return {
        "success": True,
        "hotel": hotel_name,
        "propertyID": res.get('propertyID'),
        "reservationID": res.get('reservationID'),
        "guestID": res.get('guestID'),
        "guestName": res.get('guestName'),
        "checkIn": res.get('reservationCheckIn'),
        "checkOut": res.get('reservationCheckOut'),
        "status": res.get('status')
    }

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
