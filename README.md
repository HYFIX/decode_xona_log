# Xona SNR Log Decoder & Plotter

This repository contains tools to decode raw RTCM3 stream logs and visualize the SNR (Signal-to-Noise Ratio) values for the Xona X18 LEO satellite (signals X1 and X5), with options for dual-receiver comparison, GPS SNR benchmarking, and animated video cut generation.

## Tools Included

1. **`plot_xona_snr.py`**: A Python CLI script for decoding, plotting, receiver comparison, GPS benchmarking, and CSV exporting.
2. **`xona_snr_viewer.html`**: A standalone, zero-dependency browser dashboard. Drag-and-drop one or two raw RTCM3 logs to decode and overlay plots instantly in the browser.

---

## 1. Python CLI Tool

### Installation
Make sure you have Python 3 installed. Install the optional plotting library:
```bash
pip install matplotlib
```

### Usage

#### Single File Plotting
Generate static PNG and interactive HTML plots:
```bash
python plot_xona_snr.py 2026-06-07-21-XONAH1P00004.log
```

#### Overlay GPS SNR Benchmark
Decode type `1077` (MSM7 GPS) packets, automatically select the single best GPS satellite (must have both L1 and L5 signals, with the highest average L1 SNR during the Xona pass), and overlay its L1 and L5 SNR series as benchmarks:
```bash
python plot_xona_snr.py 2026-06-07-21-XONAH1P00004.log --gps
```

#### Dual File Comparison
Overlay two receiver log files on the same timeline with the GPS benchmark satellite overlays:
```bash
python plot_xona_snr.py 2026-06-07-21-XONAH1P00004.log -c 2026-06-07-21-XONAH1P00005.log -o comparison_plot --gps
```

#### Generate Animated Video Cut
Create a dynamic time-progressing animation of the signal track:
```bash
python plot_xona_snr.py 2026-06-07-21-XONAH1P00004.log -c 2026-06-07-21-XONAH1P00005.log -o comparison_anim --gps --animate
```
*Outputs an animated `.gif` (using Pillow) or `.mp4` (if FFmpeg is installed).*

### Command Options
- `-c`, `--compare` `[FILE]`: Path to second log file to compare.
- `--gps`: Enable GPS L1/L5 dual benchmark overlays (automatically selects the single best satellite).
- `--animate` `[FILE]`: Generate an animated video cut (defaults to `.gif`).
- `-o`, `--output` `[NAME]`: Base output filename.
- `--csv` `[FILE]`: Export aligned data to CSV.
- `--open`: Automatically open interactive HTML plots in your browser.
- `--no-html` / `--no-png`: Skip generating HTML or PNG outputs.

---

## 2. Standalone Web Dashboard (`xona_snr_viewer.html`)

### Usage
1. Double-click `xona_snr_viewer.html` to open it in any modern browser.
2. Drag and drop **one or two** raw RTCM3 binary log files (`.log` or `.rtcm3`) into the drop zone.
3. The dashboard decodes the binary streams client-side in under 100ms and displays aligned SNR curves.
4. If GPS data is present, the decoder automatically selects the best GPS satellite with both L1 and L5 signals available, computes time-aligned stats, and displays them on the dashboard.
5. Use the independent checkboxes in the chart header (e.g. `Show GPS Gxx L1 Benchmark`) to toggle the benchmark lines.
6. Click **"Export CSV"** to save the aligned dataset.

---

## License
MIT
