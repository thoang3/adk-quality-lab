# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared mappings and constants for travel concierge tools."""

# Canonical mapping from internal program IDs to Seats.aero source tokens.
# Use this as the single source of truth anywhere we need to convert from
# internal profile/alert program IDs to Seats source filters.
INTERNAL_PROGRAM_TO_SEATS_SOURCE = {
    "aa_miles": "american",
    "alaska_miles": "alaska",
    "aeroplan": "aeroplan",
    "ana_miles": "ana",
    "british_airways": "british",
    "cathay_asia_miles": "cathay",
    "copa_connectmiles": "copa",
    "delta_skymiles": "delta",
    "emirates_skywards": "emirates",
    "etihad_guest": "etihad",
    "flying_blue": "flyingblue",
    "jetblue_points": "jetblue",
    "jal_miles": "jal",
    "lifemiles": "lifemiles",
    "qantas": "qantas",
    "qatar_avios": "qatar",
    "singapore_krisflyer": "singapore",
    "smiles": "smiles",
    "southwest_rr": "southwest",
    "united_miles": "united",
    "virgin_atlantic": "virginatlantic",
}

# Program name mapping for converting award API program names to internal program keys
# Used for matching against personal_valuations in user profiles
#
# Format: award_api_name -> internal_program_key
# - Award API returns: "alaska", "american", "flyingblue", "qatar" (lowercase, no spaces)
# - Internal keys: "alaska_miles", "aa_miles", "flying_blue" (used in personal_valuations)
PROGRAM_NAME_MAPPING = {
    "alaska mileage plan": "alaska_miles",
    "alaska": "alaska_miles",
    "american aadvantage": "aa_miles",
    "american": "aa_miles",
    "aa": "aa_miles",
    "flyingblue": "flying_blue",
    "flying blue": "flying_blue",
    "air france": "flying_blue",
    "air france/klm": "flying_blue",
    "airfrance": "flying_blue",
    "chase ultimate rewards": "chase_ur",
    "chase ur": "chase_ur",
    "chase": "chase_ur",
    "amex membership rewards": "amex_mr",
    "amex mr": "amex_mr",
    "amex": "amex_mr",
    "united mileageplus": "united_miles",
    "united": "united_miles",
    "southwest": "southwest_rr",
    "southwest rapid rewards": "southwest_rr",
    "southwest_rr": "southwest_rr",
    "delta skymiles": "delta_skymiles",
    "delta": "delta_skymiles",
    "british airways avios": "british_airways",
    "british airways": "british_airways",
    "british": "british_airways",
    "britishairways": "british_airways",
    "ba": "british_airways",
    "qatar avios": "qatar_avios",
    "qatar airways": "qatar_avios",
    "qatar": "qatar_avios",
    "emirates skywards": "emirates_skywards",
    "emirates": "emirates_skywards",
    "etihad": "etihad_guest",
    "etihad guest": "etihad_guest",
    "lifemiles": "lifemiles",
    "avianca": "lifemiles",
    "jal": "jal_miles",
    "jal miles": "jal_miles",
    "ana": "ana_miles",
    "ana mileage club": "ana_miles",
    "singapore": "singapore_krisflyer",
    "singapore krisflyer": "singapore_krisflyer",
    "cathay": "cathay_asia_miles",
    "cathay asia miles": "cathay_asia_miles",
    "qantas": "qantas",
    "smiles": "smiles",
    "aeroplan": "aeroplan",
    "air canada": "aeroplan",
    "aircanada": "aeroplan",
    "copa": "copa_connectmiles",
    "connectmiles": "copa_connectmiles",
    "jetblue": "jetblue_points",
    "jetblue trueblue": "jetblue_points",
    "trueblue": "jetblue_points",
    "virgin atlantic": "virgin_atlantic",
    "virgin atlantic flying club": "virgin_atlantic",
    "virginatlantic": "virgin_atlantic",
    "virgin": "virgin_atlantic",
}

# Program display names mapping (source → friendly display name)
# Used for transforming raw API source values to user-friendly program names
# in both backend (custom_api_server.py) and frontend (flight-table.js)
PROGRAM_DISPLAY_NAMES = {
    "united": "United MileagePlus",
    "american": "American AAdvantage",
    "delta": "Delta SkyMiles",
    "alaska": "Alaska Mileage Plan",
    "jetblue": "JetBlue TrueBlue",
    "southwest": "Southwest Rapid Rewards",
    "aeroplan": "Aeroplan",
    "virginatlantic": "Virgin Atlantic Flying Club",
    "virgin": "Virgin Atlantic Flying Club",
    "flyingblue": "Flying Blue",
    "british": "British Airways Avios",
    "britishairways": "British Airways Avios",
    "qantas": "Qantas Frequent Flyer",
    "qatar": "Qatar Avios",
    "qatar_avios": "Qatar Avios",
    "emirates": "Emirates Skywards",
    "emirates_skywards": "Emirates Skywards",
    "etihad": "Etihad Guest",
    "finnair": "Finnair Plus",
    "smiles": "Smiles (GOL)",
    "copa": "ConnectMiles",
    "lifemiles": "LifeMiles",
    "avianca": "LifeMiles",
    "velocity": "Velocity Miles",
    "ana": "ANA Mileage Club",
    "ana_miles": "ANA Mileage Club",
    "jal": "JAL Mileage Bank",
    "singapore": "Singapore KrisFlyer",
    "cathay": "Cathay Asia Miles",
}
