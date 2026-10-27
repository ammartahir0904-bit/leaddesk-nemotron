"""Build backend/domain/category_catalogue.json from OpenStreetMap iD tagging-schema presets.

Source: the npm package @openstreetmap/id-tagging-schema (ISC licence), the preset
list used by the iD editor, StreetComplete and Go Map!. Download a pinned version:

  V=7.3.0; D=/some/empty/dir
  curl -sSL -o $D/presets.json https://cdn.jsdelivr.net/npm/@openstreetmap/id-tagging-schema@$V/dist/presets.json
  mkdir $D/translations; for l in en es fr ...; do
    curl -sSL -o $D/translations/$l.json https://cdn.jsdelivr.net/npm/@openstreetmap/id-tagging-schema@$V/dist/translations/$l.json; done
  python3 -I scripts/build_category_catalogue.py $D $V

Each entry has 'names' (the preset name in every language), 'search' (synonyms) and
'english' (the English name and synonyms, used to resolve cross-language collisions).
Only presets for places that run as a business or organisation are kept: a fixed
key set, concrete tag values, presets that offer contact/opening-hours fields,
minus a deny-list of street furniture and public infrastructure.
"""
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

KEYS = ('shop', 'amenity', 'office', 'craft', 'tourism', 'leisure', 'healthcare')
BUSINESS_FIELDS = {'{@templates/contact}', 'phone', 'website', 'email', 'opening_hours', '{@templates/internet_access}'}
DENY = re.compile(r'^(amenity/(atm|bicycle_parking|bicycle_repair_station|bicycle_wash|car_pooling|device_charging_station|parking|'
                  r'shelter|toilets|police|fire_station|courthouse|prison|townhall|ranger_station|post_box|recycling|waste|grave_yard|'
                  r'bench|drinking_water|letter_box|vending_machine|water_point|watering_place|charging_station|compressed_air|'
                  r'baking_oven|clock|fountain|hunting_stand|lounger|telephone|ticket_validator|weighbridge|social_facility|dog_toilet|'
                  r'dressing_room|give_box|luggage_locker|parcel_locker|payment_terminal|polling_station|public_bookcase|'
                  r'sanitary_dump_station|shower|smoking_area|trolley_bay|vacuum_cleaner|kneipp_water_cure|waste_transfer_station|'
                  r'post_depot|bicycle_rental|car_sharing|taxi|grit_bin|lavoir|loading_dock|photo_booth|refugee_site|'
                  r'bbq|binoculars|boat_storage|kitchen|mortuary|motorcycle_parking|traffic_park|toy_library|water_tap|'
                  r'animal_shelter|emergency_phone|food_sharing|garden_hut|hydrant|reception_desk|feeding_place)|'
                  r'leisure/(fitness_station|garden|park|playground|nature_reserve|slipway|bird_hide|dog_park|swimming_area|'
                  r'marina_no_facilities|pitch|track|picnic_table|firepit|common|bleachers|schoolyard|outdoor_seating)|'
                  r'tourism/(information(?!/office)|picnic_site|viewpoint|artwork|camp_pitch|wilderness_hut|alpine_hut|'
                  r'camp_site/backcountry))(/|$)')
VALUE = re.compile(r'^[a-z0-9_:.;-]{1,60}$')

FOOD = {'restaurant', 'cafe', 'fast_food', 'bar', 'pub', 'biergarten', 'food_court', 'ice_cream', 'nightclub'}
HEALTH = {'dentist', 'doctors', 'clinic', 'hospital', 'pharmacy', 'veterinary', 'nursing_home', 'hospice'}
EDUCATION = {'school', 'college', 'university', 'kindergarten', 'language_school', 'driving_school', 'music_school', 'training',
             'childcare', 'library', 'prep_school', 'dancing_school', 'cooking_school', 'first_aid_school', 'flight_school',
             'surf_school', 'research_institute'}
VEHICLES = {'car_rental', 'car_wash', 'fuel', 'vehicle_inspection', 'boat_rental', 'bicycle_rental', 'motorcycle_rental',
            'car', 'car_parts', 'car_repair', 'tyres', 'motorcycle', 'motorcycle_repair', 'boat', 'bicycle', 'truck', 'caravan',
            'truck_repair', 'motorcycle_parts', 'trailer'}
FINANCE = {'bank', 'bureau_de_change', 'money_transfer', 'payment_centre', 'money_lender', 'pawnbroker'}
EVENTS = {'cinema', 'casino', 'theatre', 'arts_centre', 'events_venue', 'conference_centre', 'studio', 'gambling', 'planetarium'}
FOOD_SHOPS = {'bakery', 'butcher', 'confectionery', 'deli', 'greengrocer', 'supermarket', 'convenience', 'beverages', 'alcohol',
              'coffee', 'tea', 'pastry', 'cheese', 'seafood', 'spices', 'wine', 'chocolate', 'frozen_food', 'dairy', 'health_food',
              'nuts', 'pasta', 'water', 'farm', 'food', 'ice_cream', 'brewing_supplies', 'rice', 'tortilla'}
BEAUTY = {'beauty', 'hairdresser', 'cosmetics', 'perfumery', 'massage', 'tattoo', 'piercing', 'hairdresser_supply'}


def group(key, value):
    if key == 'shop':
        return ('Food shops' if value in FOOD_SHOPS else 'Cars and vehicles' if value in VEHICLES
                else 'Beauty and wellness' if value in BEAUTY else 'Retail')
    if key == 'amenity':
        for name, values in (('Food and drink', FOOD), ('Health', HEALTH), ('Education', EDUCATION), ('Cars and vehicles', VEHICLES),
                             ('Finance', FINANCE), ('Events and entertainment', EVENTS)):
            if value in values:
                return name
        return 'Community and services'
    return {'office': 'Professional services', 'craft': 'Crafts and trades', 'healthcare': 'Health',
            'tourism': 'Hospitality and tourism', 'leisure': 'Sport and leisure'}[key]


def fold(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ' '.join(re.sub(r'[_/,;()]+', ' ', text).split())


def as_terms(value):
    if isinstance(value, str):
        value = value.split(',')
    return [fold(v) for v in value or [] if isinstance(v, str) and v.strip()]


def all_fields(presets, pid, depth=0):
    """Fields and moreFields, following '{other/preset}' references the schema uses for inheritance."""
    preset, found = presets.get(pid) or {}, set()
    for name in (preset.get('fields') or []) + (preset.get('moreFields') or []):
        ref = name[1:-1] if name.startswith('{') and name.endswith('}') else None
        if ref in presets and depth < 5:
            found |= all_fields(presets, ref, depth + 1)
        else:
            found.add(name)
    return found


def build(folder, version):
    folder = Path(folder)
    presets = json.loads((folder / 'presets.json').read_text())
    locales = {}
    for path in sorted((folder / 'translations').glob('*.json')):
        body = json.loads(path.read_text())
        lang = next(iter(body), None)
        locales[path.stem] = ((body.get(lang) or {}).get('presets') or {}).get('presets') or {}
    english = locales.pop('en')
    items = []
    for pid, preset in sorted(presets.items()):
        parts, tags = pid.split('/'), preset.get('tags') or {}
        if parts[0] not in KEYS or len(parts) < 2 or DENY.match(pid):
            continue
        if tags.get(parts[0]) != parts[1] or not all(VALUE.match(k) and VALUE.match(v) for k, v in tags.items()):
            continue
        fields = all_fields(presets, pid)
        if not (fields & BUSINESS_FIELDS or any('contact' in f for f in fields)):
            continue
        label = (english.get(pid) or {}).get('name')
        if not label or label.startswith('{'):
            continue
        names = [fold(label)]
        search = as_terms((english.get(pid) or {}).get('terms')) + as_terms((english.get(pid) or {}).get('aliases'))
        n_en = len(search)
        for strings in locales.values():
            entry = strings.get(pid) or {}
            if isinstance(entry.get('name'), str) and not entry['name'].startswith('{'):
                names.append(fold(entry['name']))
            search += as_terms(entry.get('terms')) + as_terms(entry.get('aliases'))
        names = list(dict.fromkeys(t for t in names if 2 <= len(t) <= 60))
        en_words = [t for t in dict.fromkeys([fold(label)] + search[:n_en]) if 2 <= len(t) <= 60]
        items.append({'id': pid, 'label': label, 'group': group(parts[0], parts[1]), 'tags': tags,
                      'names': names, 'search': [t for t in dict.fromkeys(search) if 2 <= len(t) <= 60 and t not in names],
                      'english': en_words})
    return {'source': f'@openstreetmap/id-tagging-schema {version}', 'licence': 'ISC', 'built': date.today().isoformat(),
            'languages': ['en', *sorted(locales)], 'items': items}


if __name__ == '__main__':
    catalogue = build(sys.argv[1], sys.argv[2])
    out = Path(__file__).resolve().parent.parent / 'backend' / 'domain' / 'category_catalogue.json'
    out.write_text(json.dumps(catalogue, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f"{len(catalogue['items'])} categories, {len(catalogue['languages'])} languages, {out.stat().st_size // 1024} KB -> {out}")
