import os
import json
import base64
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

@app.route('/<path:filename>')
def serve_static(filename):
    import os
    if os.path.isfile(filename):
        return send_file(filename)
    return '', 404

@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({"status": "online", "hotels": [h['name'] for h in HOTELS]})

def _search_by_id(hotel, conf_number, param_name):
    """Search a single hotel by exact reservation ID. Returns (result, status) tuple."""
    if not hotel['api_key']: return None, None
    try:
        headers = {"x-api-key": hotel['api_key']}
        params = {param_name: conf_number}
        resp = requests.get(f"{CLOUDBEDS_API_URL}/getReservationsWithRateDetails",
                            headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success') and data.get('data'):
                res = data['data'][0]
                status = res.get('status', '')
                if status in ('confirmed', 'not_confirmed'):
                    return _format_res(res, hotel['name']), status
                else:
                    # Found but not in a checkable state — return status for reporting
                    return None, status
    except: pass
    return None, None


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

    # Phase 1: Search by reservationID across all hotels (exact Cloudbeds ID)
    found_status = None
    with ThreadPoolExecutor(max_workers=len(HOTELS)) as executor:
        futures = {executor.submit(_search_by_id, h, conf_number, "reservationID"): h for h in HOTELS}
        results = []
        for f in as_completed(futures):
            result, status = f.result()
            if result:
                results.append(result)
            elif status:
                found_status = status  # reservation exists but wrong status

        # Return the match (collect all, don't race)
        if results:
            chosen = results[0]
            print(f"--- SUCCESS (reservationID): Found in {chosen['hotel']} ---")
            return jsonify(chosen)

    # If reservation was found but not in a valid state, report it clearly
    if found_status:
        status_messages = {
            'canceled': 'This reservation has been canceled.',
            'checked_in': 'This reservation has already been checked in.',
            'checked_out': 'This reservation has already been checked out.',
            'no_show': 'This reservation is marked as a no-show.',
        }
        msg = status_messages.get(found_status, f'Reservation found but status is "{found_status}".')
        print(f"--- FOUND BUT STATUS: {found_status} ---")
        return jsonify({"success": False, "message": msg}), 400

    # Phase 2: Fall back to sourceReservationID (OTA/booking-site reference numbers)
    # Only for non-numeric inputs — numeric IDs are Cloudbeds reservation IDs handled by Phase 1
    if conf_number.isdigit():
        print("--- FAILED: Numeric ID not found in any hotel ---")
        return jsonify({"success": False, "message": "No confirmed booking found for this reservation ID."}), 404

    with ThreadPoolExecutor(max_workers=len(HOTELS)) as executor:
        futures = {executor.submit(_search_by_id, h, conf_number, "sourceReservationID"): h for h in HOTELS}
        results = []
        for f in as_completed(futures):
            result, status = f.result()
            if result:
                results.append(result)
            elif status:
                found_status = status

        if results:
            chosen = results[0]
            print(f"--- SUCCESS (sourceReservationID): Found in {chosen['hotel']} ---")
            return jsonify(chosen)

    if found_status:
        status_messages = {
            'canceled': 'This reservation has been canceled.',
            'checked_in': 'This reservation has already been checked in.',
            'checked_out': 'This reservation has already been checked out.',
            'no_show': 'This reservation is marked as a no-show.',
        }
        msg = status_messages.get(found_status, f'Reservation found but status is "{found_status}".')
        return jsonify({"success": False, "message": msg}), 400

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

@app.route('/api/save-guest-ids', methods=['POST'])
def save_guest_ids():
    data = request.json
    reservation_id = data.get('reservationID')
    hotel_name = data.get('hotelName')
    main_guest = data.get('mainGuest', {})       # {guestID, name, idNumber}
    additional_guests = data.get('additionalGuests', [])  # [{guestID?, name, idNumber}]

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel:
        return jsonify({"success": False, "message": "Invalid hotel"}), 400

    api_headers = {"x-api-key": hotel['api_key'], "accept": "application/json",
                   "content-type": "application/x-www-form-urlencoded"}

    # Update document number for each registered guest (has a Cloudbeds guestID)
    registered = [main_guest] + [g for g in additional_guests if g.get('guestID')]
    for g in registered:
        if g.get('guestID') and g.get('idNumber'):
            requests.put(f"{CLOUDBEDS_API_URL}/putGuest", headers=api_headers,
                         data={"guestID": str(g['guestID']), "guestDocumentNumber": g['idNumber']},
                         timeout=15)

    # Post a reservation note as audit trail (covers everyone including unregistered guests)
    lines = ["Guest ID numbers collected at self check-in:"]
    lines.append(f"  {main_guest.get('name', 'Main Guest')}: {main_guest.get('idNumber', '-')}")
    for g in additional_guests:
        lines.append(f"  {g.get('name', 'Additional Guest')}: {g.get('idNumber', '-')}")
    note = "\n".join(lines)

    requests.post(f"{CLOUDBEDS_API_URL}/postReservationNote", headers=api_headers,
                  data={"reservationID": str(reservation_id), "note": note}, timeout=15)

    print(f"--- GUEST IDs SAVED: {reservation_id} ---")
    return jsonify({"success": True})


@app.route('/api/get-guests', methods=['POST'])
def get_guests():
    data = request.json
    reservation_id = data.get('reservationID')
    hotel_name = data.get('hotelName')
    property_id = data.get('propertyID')

    hotel = next((h for h in HOTELS if h['name'] == hotel_name), None)
    if not hotel:
        return jsonify({"success": False, "message": "Invalid hotel"}), 400

    try:
        headers = {"x-api-key": hotel['api_key'], "accept": "application/json"}
        params = {"reservationID": str(reservation_id)}
        if property_id:
            params["propertyID"] = str(property_id)
        resp = requests.get(f"{CLOUDBEDS_API_URL}/getReservation", headers=headers, params=params, timeout=15)
        result = resp.json()
        if result.get('success'):
            guest_list = result['data'].get('guestList', {})
            guests = []
            for gid, g in guest_list.items():
                guests.append({
                    "guestID": g.get("guestID"),
                    "name": f"{g.get('guestFirstName', '')} {g.get('guestLastName', '')}".strip(),
                    "isMainGuest": g.get("isMainGuest", False)
                })
            # Sum adults across all assigned rooms
            assigned = result['data'].get('assigned', [])
            total_adults = sum(int(r.get('adults', 0)) for r in assigned)
            return jsonify({"success": True, "guests": guests, "totalAdults": total_adults})
        else:
            return jsonify({"success": False, "message": result.get("message", "Failed to fetch guests")})
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

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

@app.route('/api/verify-id', methods=['POST'])
def verify_id():
    """Analyze an ID document image using Groq Vision API."""
    image_file = request.files.get('image')
    guest_name = request.form.get('guestName', '')
    entered_id = request.form.get('idNumber', '')

    if not image_file:
        return jsonify({"success": False, "message": "No image provided"}), 400

    if not GROQ_API_KEY:
        return jsonify({"success": False, "message": "Vision API not configured"}), 500

    try:
        img_bytes = image_file.read()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        mime = image_file.content_type or 'image/jpeg'

        prompt = f"""You are an ID document verification system for a hotel check-in. Analyze this image of an identity document.

IMPORTANT: This is a photo taken by a hotel guest of their ID card, passport, or driver's licence. The photo may be slightly blurry, at an angle, or have glare — this is normal. Be lenient with image quality. If you can see it's an ID document with text on it, set is_valid_id to true.

Extract the information and respond with ONLY raw JSON (no markdown, no code blocks, no explanation):

{{"is_valid_id": true, "document_type": "passport", "full_name": "John Smith", "id_number": "AB123456", "expiry_date": "15/06/2028", "is_expired": false, "confidence": 0.9, "issues": []}}

Rules:
- is_valid_id: true if the image shows ANY government-issued ID (passport, driver licence, national ID, etc). Only false if clearly not an ID.
- document_type: "passport", "driver_licence", "national_id", or "other"
- full_name: The person's name as shown on the document
- id_number: The main document number (passport number, licence number, etc)
- expiry_date: Format as DD/MM/YYYY if visible, empty string if not found
- is_expired: true only if expiry date is clearly in the past, null if uncertain
- confidence: Your confidence in the extraction (0.0-1.0)
- issues: List problems ONLY if:
  - The booking name "{guest_name}" does NOT match the name on the document (name mismatch)
  - The entered ID "{entered_id}" does NOT match the document number (ID mismatch)
  - The document is expired
  - Leave empty [] if everything looks good or fields are not yet provided"""

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                        ]
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 500
            },
            timeout=30
        )

        if resp.status_code != 200:
            print(f"Groq API error: {resp.status_code} {resp.text[:200]}")
            return jsonify({"success": False, "message": "Vision API error"}), 500

        result = resp.json()
        content = result['choices'][0]['message']['content'].strip()
        print(f"--- GROQ RAW RESPONSE ---")
        print(content[:500])

        # Parse JSON from response (handle markdown code blocks if present)
        if content.startswith('```'):
            content = content.split('\n', 1)[1].rsplit('```', 1)[0].strip()

        parsed = json.loads(content)
        print(f"--- GROQ PARSED ---")
        print(json.dumps(parsed, indent=2))

        return jsonify({"success": True, "data": parsed})

    except json.JSONDecodeError as e:
        print(f"Groq JSON parse error: {e}")
        print(f"Raw content: {content[:500]}")
        # Return a permissive fallback if parsing fails
        return jsonify({"success": True, "data": {
            "is_valid_id": True, "document_type": "other", "full_name": "",
            "id_number": "", "expiry_date": "", "is_expired": None,
            "confidence": 0.5, "issues": ["Could not fully parse document — please verify manually"]
        }})
    except Exception as e:
        print(f"Verify-ID error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)
