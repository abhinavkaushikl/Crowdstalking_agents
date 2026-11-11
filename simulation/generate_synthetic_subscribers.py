#!/usr/bin/env python3
"""
Generates a fully SYNTHETIC telecom subscriber dataset for the Location
Intelligence Agent prototype. Every value is randomly generated - no real
subscriber, device, or identity data is used or represented.
"""
import csv
import random
import datetime
import os

random.seed(42)

N_ROWS = 750_000
OUT_PATH = os.path.join(os.path.dirname(__file__), "synthetic_subscribers_frankfurt.csv")

# Frankfurt am Main city bounding box
LAT_MIN, LAT_MAX = 50.0150, 50.1900
LON_MIN, LON_MAX = 8.4730, 8.8000

FIRST_NAMES = ["Lukas","Finn","Felix","Jonas","Paul","Noah","Ben","Maximilian","Elias","Leon",
               "Mia","Emma","Hannah","Sophie","Anna","Lena","Lea","Marie","Laura","Julia",
               "Ahmed","Fatima","Mehmet","Elif","Yusuf","Zeynep","Chen","Wei","Li","Ivan",
               "Olga","Maria","Giulia","Luca","Sven","Petra","Stefan","Claudia","Markus","Nina"]
LAST_NAMES = ["Mueller","Schmidt","Schneider","Fischer","Weber","Meyer","Wagner","Becker",
              "Hoffmann","Schulz","Koch","Richter","Klein","Wolf","Neumann","Zimmermann",
              "Braun","Krueger","Hartmann","Lange","Werner","Schmitt","Krause","Meier","Lehmann"]
STREETS = ["Berger Strasse","Zeil","Mainzer Landstrasse","Kaiserstrasse","Bockenheimer Landstrasse",
           "Hanauer Landstrasse","Eschersheimer Landstrasse","Leipziger Strasse","Schweizer Strasse",
           "Friedberger Landstrasse","Gruenebuger Weg","Taunusstrasse","Fahrgasse","Niddastrasse"]
DEVICE_MODELS = [
    ("Apple", "iPhone 15", "iOS 18.1", "35328111"),
    ("Apple", "iPhone 14", "iOS 17.6", "35694211"),
    ("Apple", "iPhone 13", "iOS 16.5", "35291011"),
    ("Samsung", "Galaxy S24", "Android 15", "35853811"),
    ("Samsung", "Galaxy S23", "Android 14", "35405511"),
    ("Samsung", "Galaxy A54", "Android 14", "35982711"),
    ("Google", "Pixel 9", "Android 15", "35916611"),
    ("Google", "Pixel 8", "Android 14", "35916511"),
    ("Xiaomi", "Redmi Note 13", "Android 14", "86785211"),
    ("Huawei", "P60 Pro", "Android 13 (EMUI)", "86234411"),
    ("OnePlus", "12", "Android 14", "86432211"),
    ("Nokia", "G42", "Android 13 (Go)", "35707011"),
]
PLAN_TYPES = ["Prepaid Basic", "Prepaid Plus", "Postpaid S", "Postpaid M", "Postpaid L",
              "Postpaid XL", "Family Share", "Business Pro", "Student Plan", "IoT Data Only"]
ACCOUNT_STATUS = ["ACTIVE"] * 85 + ["SUSPENDED"] * 5 + ["ACTIVE_ROAMING"] * 5 + ["CLOSED"] * 5
NETWORK_TYPES = ["5G"] * 55 + ["4G"] * 40 + ["3G"] * 5
PAYMENT_METHODS = ["SEPA Direct Debit", "Credit Card", "PayPal", "Bank Transfer", "Prepaid Voucher"]
CREDIT_TIERS = ["A", "B", "C", "D"]
GERMAN_MNC = ["01", "02", "03", "08"]  # T-Mobile, Vodafone, O2, further MVNO block

# Pre-generate ~400 synthetic cell tower sites spread across the bbox
N_TOWERS = 400
TOWERS = []
for i in range(N_TOWERS):
    t_lat = random.uniform(LAT_MIN, LAT_MAX)
    t_lon = random.uniform(LON_MIN, LON_MAX)
    TOWERS.append({
        "cell_id": f"FRA-{i:04d}",
        "lac": f"{random.randint(10000, 19999)}",
        "lat": t_lat,
        "lon": t_lon,
    })


def luhn_check_digit(number_str: str) -> str:
    digits = [int(d) for d in number_str]
    odd_sum = sum(digits[-1::-2])
    even_sum = sum(sum(divmod(d * 2, 10)) for d in digits[-2::-2])
    total = odd_sum + even_sum
    return str((10 - (total % 10)) % 10)


def random_date(start_year, end_year):
    start = datetime.date(start_year, 1, 1)
    end = datetime.date(end_year, 12, 31)
    delta = (end - start).days
    return start + datetime.timedelta(days=random.randint(0, delta))


def jitter(coord, meters=300):
    deg = meters / 111_000
    return coord + random.uniform(-deg, deg)


NOW = datetime.datetime(2026, 10, 22, 12, 0, 0)

HEADER = [
    "subscriber_id", "msisdn", "imsi", "imei", "imei_tac",
    "account_id", "customer_name", "billing_address", "dob", "national_id",
    "plan_type", "activation_date", "account_status",
    "device_make", "device_model", "os_version",
    "cell_id", "lac", "latitude", "longitude", "timestamp",
    "signal_strength_dbm", "network_type",
    "call_start_time", "call_end_time", "call_duration_sec",
    "data_volume_mb", "roaming_flag", "other_party_number",
    "monthly_charges", "payment_method", "credit_score_tier",
]


def gen_row(i):
    tower = TOWERS[random.randrange(N_TOWERS)]
    tac = random.choice(DEVICE_MODELS)
    make, model, os_version, tac_code = tac

    serial = f"{random.randint(0, 999999):06d}"
    imei_body = tac_code + serial
    imei = imei_body + luhn_check_digit(imei_body)

    msin = f"{random.randint(0, 9_999_999_999):010d}"
    imsi = "262" + random.choice(GERMAN_MNC) + msin

    msisdn = f"+4915{random.randint(0, 99999999):08d}"
    other_party = f"+4917{random.randint(0, 99999999):08d}"

    dob = random_date(1941, 2008)
    activation = random_date(2015, 2026)

    call_start = NOW - datetime.timedelta(seconds=random.randint(0, 86400))
    duration = random.randint(5, 1800)
    call_end = call_start + datetime.timedelta(seconds=duration)

    reg_time = NOW - datetime.timedelta(seconds=random.randint(0, 900))

    lat = round(jitter(tower["lat"]), 6)
    lon = round(jitter(tower["lon"]), 6)

    return [
        f"SUB-{i:08d}",
        msisdn,
        imsi,
        imei,
        tac_code,
        f"ACC-{i:08d}",
        f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
        f"{random.choice(STREETS)} {random.randint(1,180)}, {random.randint(60000,65936)} Frankfurt am Main, Germany",
        dob.isoformat(),
        f"{random.randint(10**9, 10**10 - 1)}",
        random.choice(PLAN_TYPES),
        activation.isoformat(),
        random.choice(ACCOUNT_STATUS),
        make, model, os_version,
        tower["cell_id"], tower["lac"], lat, lon, reg_time.isoformat(),
        random.randint(-115, -55),
        random.choice(NETWORK_TYPES),
        call_start.isoformat(), call_end.isoformat(), duration,
        round(random.uniform(0.1, 5000.0), 2),
        1 if random.random() < 0.03 else 0,
        other_party,
        round(random.uniform(9.99, 149.99), 2),
        random.choice(PAYMENT_METHODS),
        random.choice(CREDIT_TIERS),
    ]


def main():
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        batch = []
        for i in range(1, N_ROWS + 1):
            batch.append(gen_row(i))
            if len(batch) >= 10_000:
                writer.writerows(batch)
                batch.clear()
        if batch:
            writer.writerows(batch)
    size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
    print(f"Wrote {N_ROWS} rows to {OUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
