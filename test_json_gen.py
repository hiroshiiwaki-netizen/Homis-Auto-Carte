import json
import datetime

# ミリ秒単位の現在時刻を取得
def get_iso_now():
    return datetime.datetime.now().isoformat(timespec='milliseconds') + 'Z'

# 日付フォーマット
def format_date(dt, fmt):
    if fmt == "yyyyMMdd":
        return dt.strftime("%Y%m%d")
    elif fmt == "yyyy-MM-dd":
        return dt.strftime("%Y-%m-%d")
    elif fmt == "yyyy/MM/dd":
        return dt.strftime("%Y/%m/%d")
    elif fmt == "yyyy_MM_dd":
        return dt.strftime("%Y_%m_%d")
    elif fmt == "HH:mm":
        return dt.strftime("%H:%M")
    return ""

def get_day_of_week(dt):
    days = ["月", "火", "水", "木", "金", "土", "日"]
    return days[dt.weekday()]

# PDF.gsのcreateHomisJSON関数をPythonで再現
def create_homis_json(data):
    shooting_date = data['shootingDate']
    date_str = format_date(shooting_date, "yyyyMMdd")
    file_name = f"XP_{data['patientName']}({data['homisId']})_{date_str}.json"
    
    # 時刻計算
    day_of_week_str = get_day_of_week(shooting_date)
    # GASではgetDayで0=日曜日だが、Pythonのweekdayは0=月曜日。ロジック調整済み。
    # GAS: ["日", "月", "火", "水", "木", "金", "土"]
    # Python weekday: 0=Mon, ... 6=Sun
    # マッピング: Mon(0)->月, ..., Sun(6)->日
    
    start_time = format_date(shooting_date, "HH:mm")
    end_date = shooting_date + datetime.timedelta(minutes=10)
    end_time = format_date(end_date, "HH:mm")
    
    shooting_date_formatted = format_date(shooting_date, "yyyy_MM_dd")
    if 'requestDate' in data and data['requestDate']:
        request_date = format_date(data['requestDate'], "yyyy_MM_dd")
    else:
        request_date = shooting_date_formatted
        
    # S欄テキスト生成
    # GAS: const firstOrder = data.orders.find(o => o && o.siteName);
    first_order = next((o for o in data['orders'] if o and o.get('siteName')), None)
    s_text = ""
    if first_order:
        s_text = first_order.get('siteName', '') + "レントゲン"
        if first_order.get('purpose'):
            s_text += "\n" + first_order.get('purpose')
            
    # A/P Summaryテキスト生成
    orca_prefix = data.get('orcaNumber', "")
    ap_text = "指示医：" + data['doctorName'] + "\n"
    ap_text += f"{orca_prefix}{data['patientName']}様XP {shooting_date_formatted} XP依頼日: {request_date}\n"
    
    total_count = 0
    orders = []
    
    for idx, order in enumerate(data['orders']):
        if order and order.get('siteName'):
            # shotCountsの取得
            count = 0
            if 'shotCounts' in data and idx < len(data['shotCounts']):
                count = data['shotCounts'][idx] or 0
            
            total_count += count
            
            site_str = order.get('siteName', '')
            if order.get('direction'):
                site_str += order.get('direction')
            if order.get('position'):
                site_str += "（" + order.get('position') + "）"
                
            orders.append({
                "siteName": order.get('siteName'),
                "direction": order.get('direction', ""),
                "position": order.get('position', ""),
                "purpose": order.get('purpose', ""),
                "shotCount": count,
                "siteString": site_str
            })
            
            # A/Pテキストに追加
            if order.get('purpose'):
                ap_text += f"目的：{order.get('purpose')}\n"
            ap_text += f"部位：{site_str}\n"
            ap_text += f"撮影枚数：{count}枚\n"
            
             # LookRECリンク（最初の部位のみ）
            if idx == 0 and data.get('lookrecLink'):
                 ap_text += f"{data.get('lookrecLink')}\n"
            ap_text += "\n"

            
    ap_text += f"合計：{total_count}枚"
    
    # 曜日補正（GASのgetDayは0=日曜日だが、Pythonのweekdayは0=月なのでマップが必要）
    # GAS: ["日", "月", "火", "水", "木", "金", "土"]
    # 2026-01-30(Fri) -> GAS: 5(金)
    # Python: 4(Fri) -> 金
    gas_weekdays = ["日", "月", "火", "水", "木", "金", "土"]
    # Python weekday 0(Mon) -> index 1(月)
    # Python weekday 6(Sun) -> index 0(日)
    w_idx = (shooting_date.weekday() + 1) % 7
    day_of_week_str = gas_weekdays[w_idx]

    
    json_data = {
        "action": "homis_karte_write",
        "template": "xray_karte",
        "created_at": get_iso_now(),
        "data": {
            # 基本情報
            "orderId": data['orderId'],
            "homisId": data['homisId'],
            "patientName": data['patientName'],
            
            # 日時情報
            "shootingDate": format_date(shooting_date, "yyyy-MM-dd"),
            "shootingDateDisplay": f"{format_date(shooting_date, 'yyyy/MM/dd')}({day_of_week_str})",
            "shootingTime": start_time,
            "shootingTimeEnd": end_time,
            "requestDate": request_date,
            
            # 医師情報
            "doctorName": data['doctorName'],
            
            # ORCA番号
            "orcaNumber": data.get('orcaNumber', ""),
            
            # カルテ内容
            "sContent": s_text,
            "apContent": ap_text,
            
            # 詳細情報
            "orders": orders,
            "totalCount": total_count,
            # lookrecLink: data.lookrecLink || "" (GAS)
            "lookrecLink": data.get('lookrecLink', "")
        }
    }
    
    return json_data, file_name

# --- テスト実行 ---
print("=== JSON生成テスト開始 ===")

# 1. 通常オーダー（requestDateなし、orcaNumberなし）
normal_data = {
    "orderId": "R-Normal-12345",
    "patientName": "通常 太郎",
    "homisId": "11111",
    "doctorName": "通常 医師",
    "shootingDate": datetime.datetime(2026, 1, 30, 10, 0, 0),
    # requestDateなし
    # orcaNumberなし
    "orders": [
        {"siteName": "胸部", "direction": "正面", "position": "立位", "purpose": "定期検診"}
    ],
    "shotCounts": [2],
    "lookrecLink": "https://example.com/lookrec/normal"
}

json_normal, file_normal = create_homis_json(normal_data)
print(f"\n--- [通常オーダー] {file_normal} ---")
print(json.dumps(json_normal, indent=2, ensure_ascii=False))


# 2. 集団検診（requestDateあり、orcaNumberあり）
group_data = {
    "orderId": "R-Group-67890",
    "patientName": "集団 花子",
    "homisId": "22222",
    "doctorName": "集団 医師",
    "shootingDate": datetime.datetime(2026, 1, 30, 11, 30, 0),
    "requestDate": datetime.datetime(2026, 1, 20, 9, 0, 0),
    "orcaNumber": "98765",
    "orders": [
        {"siteName": "胸部", "direction": "正面", "position": "立位", "purpose": "集団検診"}
    ],
    "shotCounts": [1],
    "lookrecLink": "https://example.com/lookrec/group"
}

json_group, file_group = create_homis_json(group_data)
print(f"\n--- [集団検診] {file_group} ---")
print(json.dumps(json_group, indent=2, ensure_ascii=False))

print("\n=== テスト完了 ===")
