#!/usr/bin/env python3
import os
import sys
import re
import argparse
import json
import webbrowser
from datetime import datetime, timedelta

def getbitu(buff, pos, length):
    bits = 0
    for i in range(pos, pos + length):
        bits = (bits << 1) + ((buff[i // 8] >> (7 - i % 8)) & 1)
    return bits

def getbits(buff, pos, length):
    bits = getbitu(buff, pos, length)
    if length <= 0 or 32 <= length:
        return bits
    sign_bit = 1 << (length - 1)
    if bits & sign_bit:
        return bits - (1 << length)
    return bits

def crc24q(buff):
    crc = 0
    for byte in buff:
        crc ^= (byte << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF

def parse_filename_date(filepath):
    filename = os.path.basename(filepath)
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', filename)
    if match:
        year, month, day = map(int, match.groups())
        return datetime(year, month, day)
    return None

def get_gps_week_start(ref_date):
    weekday = ref_date.weekday()
    days_to_subtract = (weekday + 1) % 7
    gps_week_start = ref_date - timedelta(days=days_to_subtract)
    return datetime(gps_week_start.year, gps_week_start.month, gps_week_start.day, 0, 0, 0)

def decode_rtcm3_log(filename, target_svid=249):
    print(f"Decoding RTCM3 raw data stream: {filename}...")
    with open(filename, 'rb') as f:
        data = f.read()
    
    n = len(data)
    idx = 0
    records = []
    gps_best_snr = {}
    
    ref_date = parse_filename_date(filename)
    if not ref_date:
        ref_date = datetime.now()
        print(f"Warning: Could not parse date from filename. Using current date as reference: {ref_date.strftime('%Y-%m-%d')}")
    else:
        print(f"Reference date parsed from filename: {ref_date.strftime('%Y-%m-%d')}")
        
    gps_week_start = get_gps_week_start(ref_date)
    
    packet_count = 0
    msm7_count = 0
    gps_count = 0
    target_count = 0
    
    while idx < n - 5:
        if data[idx] == 0xD3:
            length = ((data[idx+1] & 0x03) << 8) | data[idx+2]
            if idx + 6 + length <= n:
                packet_bytes = data[idx : idx + 6 + length]
                calc_crc = crc24q(packet_bytes[:-3])
                expected_crc = (packet_bytes[-3] << 16) | (packet_bytes[-2] << 8) | packet_bytes[-1]
                if calc_crc == expected_crc:
                    packet_count += 1
                    msg_type = (packet_bytes[3] << 4) | (packet_bytes[4] >> 4)
                    
                    if msg_type == 4045: # Proprietary LEO/XONA
                        subtype = ((packet_bytes[4] & 0x01) << 8) | packet_bytes[5]
                        if subtype == 7: # MSM7 for LEO/XONA
                            msm7_count += 1
                            bit_pos = 48
                            staid = getbitu(packet_bytes, bit_pos, 12); bit_pos += 12
                            tow = getbitu(packet_bytes, bit_pos, 30) * 0.001; bit_pos += 30
                            sync = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                            iod = getbitu(packet_bytes, bit_pos, 3); bit_pos += 3
                            time_s = getbitu(packet_bytes, bit_pos, 7); bit_pos += 7
                            clk_str = getbitu(packet_bytes, bit_pos, 2); bit_pos += 2
                            clk_ext = getbitu(packet_bytes, bit_pos, 2); bit_pos += 2
                            smooth = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                            tint_s = getbitu(packet_bytes, bit_pos, 3); bit_pos += 3
                            
                            sats = []
                            for j in range(1, 65):
                                mask = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                                if mask:
                                    sats.append(j)
                            
                            sigs = []
                            for j in range(1, 5):
                                mask = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                                if mask:
                                    sigs.append(j)
                                    
                            page = getbitu(packet_bytes, bit_pos, 28); bit_pos += 28
                            
                            nsat = len(sats)
                            nsig = len(sigs)
                            
                            cellmask = []
                            ncell = 0
                            for j in range(nsat * nsig):
                                mask = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                                cellmask.append(mask)
                                if mask:
                                    ncell += 1
                                    
                            bit_pos += nsat * 36
                            cnr_start = bit_pos + ncell * 55
                            
                            target_r_idx = -1
                            for r_idx, sat in enumerate(sats):
                                svid = page * 64 + sat
                                if svid == target_svid:
                                    target_r_idx = r_idx
                                    break
                                    
                            if target_r_idx != -1:
                                target_count += 1
                                cell_idx = 0
                                snr_x1 = None
                                snr_x5 = None
                                
                                for r_idx, sat in enumerate(sats):
                                    for s_idx, sig in enumerate(sigs):
                                        if cellmask[r_idx * nsig + s_idx]:
                                            if r_idx == target_r_idx:
                                                cnr_val = getbitu(packet_bytes, cnr_start + cell_idx * 10, 10) * 0.0625
                                                if sig == 1: # X1
                                                    snr_x1 = round(cnr_val, 4)
                                                elif sig == 2: # X5
                                                    snr_x5 = round(cnr_val, 4)
                                            cell_idx += 1
                                
                                epoch_time = gps_week_start + timedelta(seconds=tow)
                                records.append({
                                    'tow': tow,
                                    'time': epoch_time.strftime('%Y-%m-%d %H:%M:%S'),
                                    'x1': snr_x1,
                                    'x5': snr_x5
                                })
                    elif msg_type == 1077: # GPS MSM7
                        gps_count += 1
                        bit_pos = 36
                        staid = getbitu(packet_bytes, bit_pos, 12); bit_pos += 12
                        tow = getbitu(packet_bytes, bit_pos, 30) * 0.001; bit_pos += 30
                        sync = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                        iod = getbitu(packet_bytes, bit_pos, 3); bit_pos += 3
                        time_s = getbitu(packet_bytes, bit_pos, 7); bit_pos += 7
                        clk_str = getbitu(packet_bytes, bit_pos, 2); bit_pos += 2
                        clk_ext = getbitu(packet_bytes, bit_pos, 2); bit_pos += 2
                        smooth = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                        tint_s = getbitu(packet_bytes, bit_pos, 3); bit_pos += 3
                        
                        sats = []
                        for j in range(1, 65):
                            mask = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                            if mask:
                                sats.append(j)
                        
                        sigs = []
                        for j in range(1, 33):
                            mask = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                            if mask:
                                sigs.append(j)
                                
                        nsat = len(sats)
                        nsig = len(sigs)
                        
                        cellmask = []
                        ncell = 0
                        for j in range(nsat * nsig):
                            mask = getbitu(packet_bytes, bit_pos, 1); bit_pos += 1
                            cellmask.append(mask)
                            if mask:
                                ncell += 1
                                
                        bit_pos += nsat * 36
                        cnr_start = bit_pos + ncell * 55
                        
                        snrs = []
                        for c in range(ncell):
                            cnr_val = getbitu(packet_bytes, cnr_start + c * 10, 10) * 0.0625
                            snrs.append(cnr_val)
                            
                        if snrs:
                            gps_best_snr[tow] = max(snrs)

                    idx += 6 + length
                    continue
        idx += 1
        
    print(f"Decoded {packet_count} valid RTCM3 packets.")
    print(f"Found {msm7_count} LEO/Xona MSM7 packets.")
    print(f"Found {gps_count} GPS MSM7 packets.")
    print(f"Found {target_count} epochs containing Xona X18 data.")
    return records, gps_best_snr

def merge_time_series(records1, records2):
    all_times = sorted(list(set([r['time'] for r in records1] + [r['time'] for r in records2])))
    dict1 = {r['time']: r for r in records1}
    dict2 = {r['time']: r for r in records2}
    
    merged = []
    for t in all_times:
        r1 = dict1.get(t)
        r2 = dict2.get(t)
        merged.append({
            'time': t,
            'tow': r1['tow'] if r1 else (r2['tow'] if r2 else None),
            'x1_1': r1['x1'] if r1 else None,
            'x5_1': r1['x5'] if r1 else None,
            'x1_2': r2['x1'] if r2 else None,
            'x5_2': r2['x5'] if r2 else None
        })
    return merged, all_times

def generate_html_plot(records1, records2, gps_best_snr, log_filepath1, log_filepath2, show_gps, output_html_path):
    log_name1 = os.path.basename(log_filepath1)
    log_name2 = os.path.basename(log_filepath2) if log_filepath2 else None
    
    if log_name2:
        merged, times = merge_time_series(records1, records2)
        x1_1 = [m['x1_1'] for m in merged]
        x5_1 = [m['x5_1'] for m in merged]
        x1_2 = [m['x1_2'] for m in merged]
        x5_2 = [m['x5_2'] for m in merged]
        gps_vals = [gps_best_snr.get(m['tow'], None) for m in merged] if show_gps else []
        title_text = "Xona X18 SNR Comparison"
        subtitle_text = f"Comparing: <strong>{log_name1}</strong> (Solid) vs <strong>{log_name2}</strong> (Dashed)"
    else:
        times = [r['time'] for r in records1]
        x1_1 = [r['x1'] for r in records1]
        x5_1 = [r['x5'] for r in records1]
        x1_2 = []
        x5_2 = []
        gps_vals = [gps_best_snr.get(r['tow'], None) for r in records1] if show_gps else []
        title_text = "Xona X18 SNR Analysis"
        subtitle_text = f"Decoded from RTCM3 raw stream: <strong>{log_name1}</strong>"
        
    file2_stats_html = ""
    gps_control_html = ""
    if show_gps:
        gps_control_html = """
            <div class="control-row">
                <input type="checkbox" id="chk-gps" checked>
                <label for="chk-gps">Show GPS SNR Benchmark</label>
            </div>
        """
    if log_name2:
        file2_stats_html = f"""
            <h3 class="stats-section-title">File 2: {log_name2}</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-title">Epochs</div>
                    <div class="stat-value">{len(records2)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X1 Max SNR</div>
                    <div class="stat-value x1-2" id="x1-max-2">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X1 Mean SNR</div>
                    <div class="stat-value x1-2" id="x1-mean-2">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X5 Max SNR</div>
                    <div class="stat-value x5-2" id="x5-max-2">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X5 Mean SNR</div>
                    <div class="stat-value x5-2" id="x5-mean-2">-</div>
                </div>
            </div>
        """
        
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title_text}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #151c2c;
            --text-color: #f3f4f6;
            --text-muted: #9ca3af;
            --primary: #3b82f6;
            --accent-x1: #3b82f6;
            --accent-x5: #10b981;
            --accent2-x1: #f59e0b;
            --accent2-x5: #ef4444;
            --border-color: #1f2937;
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: 'Inter', sans-serif;
            margin: 0;
            padding: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            width: 100%;
        }}
        header {{
            margin-bottom: 24px;
            text-align: center;
        }}
        h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.5rem;
            font-weight: 800;
            margin: 0 0 8px 0;
            background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 50%, #10b981 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        p.subtitle {{
            color: var(--text-muted);
            font-size: 1.1rem;
            margin: 0;
        }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
            margin-bottom: 24px;
        }}
        .stats-container {{
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stats-section-title {{
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 4px;
            margin: 0;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }}
        .stat-card {{
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 14px;
            text-align: center;
        }}
        .stat-title {{
            color: var(--text-muted);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }}
        .stat-value {{
            font-size: 1.6rem;
            font-weight: 700;
            font-family: 'Outfit', sans-serif;
        }}
        .stat-value.x1 {{ color: var(--accent-x1); }}
        .stat-value.x5 {{ color: var(--accent-x5); }}
        .stat-value.x1-2 {{ color: var(--accent2-x1); }}
        .stat-value.x5-2 {{ color: var(--accent2-x5); }}
        .chart-container {{
            position: relative;
            height: 520px;
            width: 100%;
        }}
        .control-row {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
        }}
        .control-row input {{
            width: 16px;
            height: 16px;
            cursor: pointer;
        }}
        .control-row label {{
            font-size: 0.9rem;
            color: var(--text-muted);
            cursor: pointer;
            user-select: none;
        }}
        footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-top: auto;
            padding-top: 24px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{title_text}</h1>
            <p class="subtitle">{subtitle_text}</p>
        </header>

        <div class="stats-container">
            <h3 class="stats-section-title">File 1: {log_name1}</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-title">Epochs</div>
                    <div class="stat-value">{len(records1)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X1 Max SNR</div>
                    <div class="stat-value x1" id="x1-max">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X1 Mean SNR</div>
                    <div class="stat-value x1" id="x1-mean">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X5 Max SNR</div>
                    <div class="stat-value x5" id="x5-max">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">X5 Mean SNR</div>
                    <div class="stat-value x5" id="x5-mean">-</div>
                </div>
            </div>
            {file2_stats_html}
        </div>

        <div class="card">
            {gps_control_html}
            <div class="chart-container">
                <canvas id="snrChart"></canvas>
            </div>
        </div>

        <footer>
            Xona RTCM3 Decoder Tool &bull; Comparison Dashboard
        </footer>
    </div>

    <script>
        const times = {json.dumps(times)};
        const x1_1 = {json.dumps(x1_1)};
        const x5_1 = {json.dumps(x5_1)};
        const x1_2 = {json.dumps(x1_2)};
        const x5_2 = {json.dumps(x5_2)};
        const gps = {json.dumps(gps_vals)};

        // Filter valid data points for stats
        const validX1_1 = x1_1.filter(v => v !== null && v !== undefined);
        const validX5_1 = x5_1.filter(v => v !== null && v !== undefined);
        const validX1_2 = x1_2.filter(v => v !== null && v !== undefined);
        const validX5_2 = x5_2.filter(v => v !== null && v !== undefined);

        if (validX1_1.length > 0) {{
            const maxVal = Math.max(...validX1_1);
            const meanVal = validX1_1.reduce((a, b) => a + b, 0) / validX1_1.length;
            document.getElementById('x1-max').innerText = maxVal.toFixed(2) + ' dB-Hz';
            document.getElementById('x1-mean').innerText = meanVal.toFixed(2) + ' dB-Hz';
        }}
        if (validX5_1.length > 0) {{
            const maxVal = Math.max(...validX5_1);
            const meanVal = validX5_1.reduce((a, b) => a + b, 0) / validX5_1.length;
            document.getElementById('x5-max').innerText = maxVal.toFixed(2) + ' dB-Hz';
            document.getElementById('x5-mean').innerText = meanVal.toFixed(2) + ' dB-Hz';
        }}
        
        if (x1_2.length > 0 && validX1_2.length > 0) {{
            const maxVal = Math.max(...validX1_2);
            const meanVal = validX1_2.reduce((a, b) => a + b, 0) / validX1_2.length;
            document.getElementById('x1-max-2').innerText = maxVal.toFixed(2) + ' dB-Hz';
            document.getElementById('x1-mean-2').innerText = meanVal.toFixed(2) + ' dB-Hz';
        }}
        if (x5_2.length > 0 && validX5_2.length > 0) {{
            const maxVal = Math.max(...validX5_2);
            const meanVal = validX5_2.reduce((a, b) => a + b, 0) / validX5_2.length;
            document.getElementById('x5-max-2').innerText = maxVal.toFixed(2) + ' dB-Hz';
            document.getElementById('x5-mean-2').innerText = meanVal.toFixed(2) + ' dB-Hz';
        }}

        // Setup datasets
        const datasets = [
            {{
                label: 'File 1 X1 SNR (1X)',
                data: x1_1,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.05)',
                borderWidth: 2,
                pointRadius: 1,
                pointHoverRadius: 4,
                spanGaps: true,
                tension: 0.1
            }},
            {{
                label: 'File 1 X5 SNR (5X)',
                data: x5_1,
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.05)',
                borderWidth: 2,
                pointRadius: 1,
                pointHoverRadius: 4,
                spanGaps: true,
                tension: 0.1
            }}
        ];

        if (x1_2.length > 0) {{
            datasets.push({{
                label: 'File 2 X1 SNR (1X)',
                data: x1_2,
                borderColor: '#f59e0b',
                backgroundColor: 'rgba(245, 158, 11, 0.05)',
                borderWidth: 2,
                borderDash: [5, 5],
                pointRadius: 1,
                pointHoverRadius: 4,
                spanGaps: true,
                tension: 0.1
            }});
            datasets.push({{
                label: 'File 2 X5 SNR (5X)',
                data: x5_2,
                borderColor: '#ef4444',
                backgroundColor: 'rgba(239, 68, 68, 0.05)',
                borderWidth: 2,
                borderDash: [5, 5],
                pointRadius: 1,
                pointHoverRadius: 4,
                spanGaps: true,
                tension: 0.1
            }});
        }}
        
        if (gps.length > 0) {{
            datasets.push({{
                label: 'Best GPS SNR (Benchmark)',
                data: gps,
                borderColor: '#9ca3af',
                backgroundColor: 'transparent',
                borderWidth: 1.5,
                borderDash: [3, 3],
                pointRadius: 0,
                pointHoverRadius: 3,
                spanGaps: true,
                tension: 0.1
            }});
        }}

        const ctx = document.getElementById('snrChart').getContext('2d');
        const chart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: times,
                datasets: datasets
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false
                }},
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{
                            color: '#9ca3af',
                            font: {{ family: 'Inter' }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{ color: '#1f2937' }},
                        ticks: {{
                            color: '#9ca3af',
                            font: {{ family: 'Inter' }},
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 12,
                            callback: function(val, index) {{
                                const label = this.getLabelForValue(val);
                                if (label && label.includes(' ')) {{
                                    return label.split(' ')[1];
                                }}
                                return label;
                            }}
                        }}
                    }},
                    y: {{
                        grid: {{ color: '#1f2937' }},
                        title: {{
                            display: true,
                            text: 'SNR (dB-Hz)',
                            color: '#9ca3af',
                            font: {{ family: 'Inter', weight: 'bold' }}
                        }},
                        ticks: {{
                            color: '#9ca3af',
                            font: {{ family: 'Inter' }}
                        }}
                    }}
                }}
            }}
        }});
        
        const chkGps = document.getElementById('chk-gps');
        if (chkGps) {{
            chkGps.addEventListener('change', (e) => {{
                const idx = chart.data.datasets.findIndex(d => d.label === 'Best GPS SNR (Benchmark)');
                if (idx !== -1) {{
                    chart.setDatasetVisibility(idx, e.target.checked);
                    chart.update();
                }}
            }});
        }}
    </script>
</body>
</html>
"""
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Interactive HTML dashboard saved to: {output_html_path}")

def plot_static_png(records1, records2, gps_best_snr, log_filepath1, log_filepath2, show_gps, output_png_path):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))
        
        times1 = [datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S') for r in records1]
        x1_1 = [r['x1'] for r in records1]
        x5_1 = [r['x5'] for r in records1]
        
        ax.plot(times1, x1_1, label='File 1 X1 SNR (1X)', color='#3b82f6', linewidth=1.5)
        ax.plot(times1, x5_1, label='File 1 X5 SNR (5X)', color='#10b981', linewidth=1.5)
        
        title_text = f"Xona X18 SNR values over Time\nFile 1: {os.path.basename(log_filepath1)}"
        
        if records2 and log_filepath2:
            times2 = [datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S') for r in records2]
            x1_2 = [r['x1'] for r in records2]
            x5_2 = [r['x5'] for r in records2]
            
            ax.plot(times2, x1_2, label='File 2 X1 SNR (1X)', color='#f59e0b', linestyle='--', linewidth=1.5)
            ax.plot(times2, x5_2, label='File 2 X5 SNR (5X)', color='#ef4444', linestyle='--', linewidth=1.5)
            
            title_text += f" vs File 2: {os.path.basename(log_filepath2)}"
            
        if show_gps and gps_best_snr:
            gps_times = sorted(gps_best_snr.keys())
            # Map GPS times to datetime objects
            # To do this correctly, we need the reference date from filename 1
            ref_date = parse_filename_date(log_filepath1) or datetime.now()
            gps_week_start = get_gps_week_start(ref_date)
            gps_dts = [gps_week_start + timedelta(seconds=t) for t in gps_times]
            gps_vals = [gps_best_snr[t] for t in gps_times]
            
            ax.plot(gps_dts, gps_vals, label='Best GPS SNR (Benchmark)', color='#9ca3af', linestyle=':', linewidth=1)
            
        ax.set_title(title_text, fontsize=12, fontweight='bold', pad=15)
        ax.set_xlabel('Time (GPS)', fontsize=11, labelpad=10)
        ax.set_ylabel('SNR (dB-Hz)', fontsize=11, labelpad=10)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        fig.autofmt_xdate()
        
        ax.grid(color='#2a2a2a', linestyle='--', linewidth=0.5)
        ax.legend(loc='upper right', framealpha=0.5)
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#555555')
        ax.spines['bottom'].set_color('#555555')
        
        plt.tight_layout()
        plt.savefig(output_png_path, dpi=150)
        plt.close()
        print(f"Static PNG plot saved to: {output_png_path}")
        return True
    except ImportError:
        print("Warning: matplotlib not installed. Skipping static PNG plot generation.")
        return False

def plot_animation(records1, records2, gps_best_snr, log_filepath1, log_filepath2, show_gps, output_video_path):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.animation as animation
        import matplotlib.dates as mdates
        
        print(f"Generating animated video cut to {output_video_path}...")
        
        if records2 and log_filepath2:
            merged, times_str = merge_time_series(records1, records2)
            times = [datetime.strptime(t, '%Y-%m-%d %H:%M:%S') for t in times_str]
            x1_1 = [m['x1_1'] for m in merged]
            x5_1 = [m['x5_1'] for m in merged]
            x1_2 = [m['x1_2'] for m in merged]
            x5_2 = [m['x5_2'] for m in merged]
            gps_vals = [gps_best_snr.get(m['tow'], None) for m in merged] if show_gps else []
        else:
            times = [datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S') for r in records1]
            x1_1 = [r['x1'] for r in records1]
            x5_1 = [r['x5'] for r in records1]
            x1_2 = []
            x5_2 = []
            gps_vals = [gps_best_snr.get(r['tow'], None) for r in records1] if show_gps else []
            
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5.5))
        
        ax.set_xlim(min(times), max(times))
        
        all_y = [y for y in x1_1 + x5_1 + x1_2 + x5_2 + gps_vals if y is not None]
        min_y = min(all_y) - 2 if all_y else 20
        max_y = max(all_y) + 2 if all_y else 60
        ax.set_ylim(min_y, max_y)
        
        ax.set_xlabel('Time (GPS)', fontsize=10, labelpad=8)
        ax.set_ylabel('SNR (dB-Hz)', fontsize=10, labelpad=8)
        
        title_text = f"Xona X18 SNR Tracking\nFile 1: {os.path.basename(log_filepath1)}"
        if records2:
            title_text += f" vs File 2: {os.path.basename(log_filepath2)}"
        ax.set_title(title_text, fontsize=11, fontweight='bold', pad=12)
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        fig.autofmt_xdate()
        ax.grid(color='#2a2a2a', linestyle='--', linewidth=0.5)
        
        line_x1_1, = ax.plot([], [], label='File 1 X1 SNR', color='#3b82f6', linewidth=1.5)
        line_x5_1, = ax.plot([], [], label='File 1 X5 SNR', color='#10b981', linewidth=1.5)
        
        lines = [line_x1_1, line_x5_1]
        
        if x1_2:
            line_x1_2, = ax.plot([], [], label='File 2 X1 SNR', color='#f59e0b', linestyle='--', linewidth=1.5)
            line_x5_2, = ax.plot([], [], label='File 2 X5 SNR', color='#ef4444', linestyle='--', linewidth=1.5)
            lines.extend([line_x1_2, line_x5_2])
            
        if show_gps and gps_vals:
            line_gps, = ax.plot([], [], label='Best GPS SNR (Benchmark)', color='#9ca3af', linestyle=':', linewidth=1)
            lines.append(line_gps)
            
        ax.legend(loc='upper right', framealpha=0.5)
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#555555')
        ax.spines['bottom'].set_color('#555555')
        
        def init():
            for line in lines:
                line.set_data([], [])
            return lines
            
        n_points = len(times)
        step = max(1, n_points // 120)
        
        frames = list(range(0, n_points, step))
        if not frames or frames[-1] != n_points - 1:
            frames.append(n_points - 1)
            
        def animate(frame_idx):
            idx_limit = frame_idx + 1
            t_slice = times[:idx_limit]
            
            line_x1_1.set_data(t_slice, x1_1[:idx_limit])
            line_x5_1.set_data(t_slice, x5_1[:idx_limit])
            
            curr_lines = [line_x1_1, line_x5_1]
            
            if x1_2:
                line_x1_2.set_data(t_slice, x1_2[:idx_limit])
                line_x5_2.set_data(t_slice, x5_2[:idx_limit])
                curr_lines.extend([line_x1_2, line_x5_2])
                
            if show_gps and gps_vals:
                line_gps.set_data(t_slice, gps_vals[:idx_limit])
                curr_lines.append(line_gps)
                
            return curr_lines
            
        ani = animation.FuncAnimation(fig, animate, frames=frames, init_func=init, blit=True, interval=50)
        
        if output_video_path.endswith('.gif'):
            writer = animation.PillowWriter(fps=20)
            ani.save(output_video_path, writer=writer)
        else:
            writer = animation.FFMpegWriter(fps=20, codec='libx264')
            ani.save(output_video_path, writer=writer)
            
        plt.close()
        print(f"Animated video cut saved to: {output_video_path}")
        return True
    except ImportError as e:
        print(f"Warning: Failed to generate animation. Required libraries missing or error occurred: {e}")
        return False
    except Exception as e:
        print(f"Warning: Failed to save video animation: {e}")
        print("Note: MP4 animation requires FFmpeg. You can save as .gif by specifying a .gif extension.")
        return False

def export_csv(records1, records2, gps_best_snr, show_gps, output_csv_path):
    import csv
    with open(output_csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        if records2:
            merged, _ = merge_time_series(records1, records2)
            headers = ['Time (GPS)', 'File1 X1 SNR (dB-Hz)', 'File1 X5 SNR (dB-Hz)', 'File2 X1 SNR (dB-Hz)', 'File2 X5 SNR (dB-Hz)']
            if show_gps:
                headers.append('Best GPS SNR (dB-Hz)')
            writer.writerow(headers)
            for m in merged:
                row = [m['time'], m['x1_1'], m['x5_1'], m['x1_2'], m['x5_2']]
                if show_gps:
                    row.append(gps_best_snr.get(m['tow'], ""))
                writer.writerow(row)
        else:
            headers = ['Time (GPS)', 'TOW (s)', 'X1 SNR (dB-Hz)', 'X5 SNR (dB-Hz)']
            if show_gps:
                headers.append('Best GPS SNR (dB-Hz)')
            writer.writerow(headers)
            for r in records1:
                row = [r['time'], r['tow'], r['x1'], r['x5']]
                if show_gps:
                    row.append(gps_best_snr.get(r['tow'], ""))
                writer.writerow(row)
    print(f"CSV data exported to: {output_csv_path}")

def main():
    parser = argparse.ArgumentParser(description="Decode Xona X18 SNR values from RTCM3 log and plot them.")
    parser.add_argument("file", help="Path to raw RTCM3 stream log file (e.g. 2026-06-07-21-XONAH1P00004.log)")
    parser.add_argument("-c", "--compare", help="Path to second raw RTCM3 stream log file to compare against")
    parser.add_argument("-o", "--output", help="Base filename for outputs (default is log filename in current directory)")
    parser.add_argument("--csv", help="Path to export decoded data to CSV")
    parser.add_argument("--gps", action="store_true", help="Display best GPS satellite SNR for benchmark comparison")
    parser.add_argument("--no-html", action="store_true", help="Do not generate interactive HTML plot")
    parser.add_argument("--no-png", action="store_true", help="Do not generate static PNG plot")
    parser.add_argument("--animate", nargs='?', const='auto', help="Generate an animated video cut (e.g. plot.gif or plot.mp4)")
    parser.add_argument("--open", action="store_true", help="Automatically open interactive HTML plot in web browser")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}")
        sys.exit(1)
        
    records1, gps_best_snr = decode_rtcm3_log(args.file)
    if not records1:
        print("No Xona X18 observations decoded from the first file. Exiting.")
        sys.exit(0)
        
    records2 = []
    if args.compare:
        if not os.path.exists(args.compare):
            print(f"Error: Comparison file not found: {args.compare}")
            sys.exit(1)
        records2, gps_best_snr2 = decode_rtcm3_log(args.compare)
        if not records2:
            print("Warning: No Xona X18 observations decoded from the comparison file.")
            
        # Merge both receivers' GPS best SNR lists if comparison file has one too
        if args.gps:
            for tow, val in gps_best_snr2.items():
                if tow not in gps_best_snr or val > gps_best_snr[tow]:
                    gps_best_snr[tow] = val
            
    base_name = args.output
    if not base_name:
        base_name = os.path.splitext(os.path.basename(args.file))[0]
        if args.compare:
            base_name += "_vs_" + os.path.splitext(os.path.basename(args.compare))[0]
            
    if args.csv:
        export_csv(records1, records2, gps_best_snr, args.gps, args.csv)
        
    if not args.no_png:
        plot_static_png(records1, records2, gps_best_snr, args.file, args.compare, args.gps, f"{base_name}.png")
        
    if not args.no_html:
        html_path = os.path.abspath(f"{base_name}.html")
        generate_html_plot(records1, records2, gps_best_snr, args.file, args.compare, args.gps, html_path)
        if args.open:
            webbrowser.open(f"file:///{html_path}")
            
    if args.animate:
        anim_path = args.animate
        if anim_path == 'auto':
            anim_path = f"{base_name}.gif"
        plot_animation(records1, records2, gps_best_snr, args.file, args.compare, args.gps, anim_path)

if __name__ == "__main__":
    main()
