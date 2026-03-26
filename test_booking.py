"""
Utility script to create/delete dummy reservations in Cloudbeds for testing.

Usage:
    python test_booking.py create    # Create a dummy reservation
    python test_booking.py delete RESERVATION_ID PROPERTY_ID  # Cancel a reservation
"""

import os
import sys
import requests
import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

CLOUDBEDS_API_URL = "https://api.cloudbeds.com/api/v1.3"

# Use the first API key
keys_str = os.getenv("CLOUDBEDS_API_KEYS", "")
api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]

# Override: use dedicated test key with reservation read/write scope
API_KEY = "cbat_bNFVy31gZeJRxzUfmKvz9tFeXOJxMWY1"
api_keys = [API_KEY]
HEADERS = {"x-api-key": API_KEY, "accept": "application/json"}


def create_reservation():
    """Create a dummy reservation for testing the check-in flow."""
    # Fetch all room types across all API keys
    print("Fetching available room types...")

    all_room_types = []
    for i, key in enumerate(api_keys):
        headers = {"x-api-key": key, "accept": "application/json"}
        resp = requests.get(f"{CLOUDBEDS_API_URL}/getRoomTypes", headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("data"):
                for rt in data["data"]:
                    rt["_api_key"] = key
                    rt["_hotel_index"] = i
                    all_room_types.append(rt)

    if not all_room_types:
        print("No room types found across any hotel.")
        sys.exit(1)

    # Try each room type with multiple date ranges
    date_offsets = [(1, 2), (3, 4), (7, 8), (14, 15), (30, 31), (60, 61)]

    for room in all_room_types:
        room_type_id = room["roomTypeID"]
        property_id = room.get("propertyID", "")
        key = room["_api_key"]
        headers = {"x-api-key": key, "accept": "application/json",
                   "content-type": "application/x-www-form-urlencoded"}

        print(f"\nTrying room: {room.get('roomTypeName', room_type_id)} (Property: {property_id})")

        for start_off, end_off in date_offsets:
            start = (datetime.datetime.now() + datetime.timedelta(days=start_off)).strftime("%Y-%m-%d")
            end = (datetime.datetime.now() + datetime.timedelta(days=end_off)).strftime("%Y-%m-%d")

            payload = {
                "startDate": start,
                "endDate": end,
                "guestFirstName": "Test",
                "guestLastName": "Guest",
                "guestCountry": "US",
                "guestZip": "10001",
                "guestEmail": "testguest@example.com",
                "guestPhone": "+1234567890",
                "rooms[0][roomTypeID]": str(room_type_id),
                "rooms[0][quantity]": "1",
                "adults[0][roomTypeID]": str(room_type_id),
                "adults[0][quantity]": "1",
                "children[0][roomTypeID]": str(room_type_id),
                "children[0][quantity]": "0",
                "paymentMethod": "cash",
                "sendEmailConfirmation": "false",
            }
            if property_id:
                payload["propertyID"] = str(property_id)

            print(f"  Dates {start} -> {end}...", end=" ")
            resp = requests.post(
                f"{CLOUDBEDS_API_URL}/postReservation",
                headers=headers,
                data=payload,
                timeout=15,
            )

            result = resp.json()
            if result.get("success"):
                res_id = result.get("reservationID")
                print(f"SUCCESS!")
                print(f"\n  Reservation created successfully!")
                print(f"  Reservation ID: {res_id}")
                print(f"  Check-in: {start}")
                print(f"  Check-out: {end}")
                print(f"  Property ID: {property_id}")
                print(f"\n  Use this ID in the check-in app to test.")
                print(f"\n  To delete later: python test_booking.py delete {res_id} {property_id}")
                return
            else:
                msg = result.get("message", "Unknown error")
                print(f"FAIL ({msg[:60]})")

    print("\nCould not create reservation with any room type or date range.")


def cancel_reservation(reservation_id, property_id):
    """Cancel/delete a reservation by setting status to 'canceled'."""
    print(f"Canceling reservation {reservation_id}...")

    payload = {
        "reservationID": str(reservation_id),
        "status": "canceled",
    }
    if property_id:
        payload["propertyID"] = str(property_id)

    resp = requests.put(
        f"{CLOUDBEDS_API_URL}/putReservation",
        headers={**HEADERS, "content-type": "application/x-www-form-urlencoded"},
        data=payload,
        timeout=15,
    )

    result = resp.json()
    print(f"\nResponse ({resp.status_code}):")
    if result.get("success"):
        print(f"  Reservation {reservation_id} canceled successfully!")
    else:
        print(f"  Failed: {result}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "create":
        create_reservation()
    elif action == "delete" or action == "cancel":
        if len(sys.argv) < 3:
            print("Usage: python test_booking.py delete RESERVATION_ID [PROPERTY_ID]")
            sys.exit(1)
        res_id = sys.argv[2]
        prop_id = sys.argv[3] if len(sys.argv) > 3 else ""
        cancel_reservation(res_id, prop_id)
    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)
