# Nilla Daily Mart — implementasi inti v0.2

Versi ini mengganti demo localStorage dengan aplikasi satu toko berbasis SQLite, API Python dan antarmuka sesuai peran. Tidak ada penjualan atau identitas pelanggan contoh di database operasional. Ini rilis evaluasi lokal, belum siap produksi dan belum mencakup seluruh master prompt.

## Jalankan

### Windows tanpa terminal

1. Ekstrak ZIP ke folder biasa, misalnya `Documents\\Nilla-Daily-Mart-v0.2`.
2. Klik dua kali `Jalankan-Nilla-Daily-Mart.bat`.
3. Jika Windows meminta izin, pilih **Run**. Browser akan membuka aplikasi secara otomatis.
4. Biarkan jendela hitam tetap terbuka selama aplikasi digunakan. Tekan `Ctrl+C` pada jendela tersebut saat selesai.

Jika muncul pesan Python belum terpasang, instal Python 3 dari `python.org/downloads`. Saat memasang, centang **Add Python to PATH**, lalu klik berkas peluncur lagi.

### Terminal

Prasyarat: Python 3.10+ beserta database zona waktu IANA (tersedia pada Linux environment ini). Node hanya diperlukan untuk menggunakan pintasan npm.

```sh
cd /workspace/APLIKASI-POS
npm start
# Alternatif tanpa Node:
python3 backend.py
```

Port bawaan 4173, bind 127.0.0.1. Gunakan browser pada mesin yang menjalankan aplikasi. Buat akun owner pertama pada layar awal; kata sandi minimal 12 karakter, tidak ada akun/password bawaan. Akun owner pertama hanya dapat dibuat sekali. Belum ada deployment publik atau integrasi payment gateway.

Konfigurasi: `PORT`, `HOST`, `NILLA_DB` (default `data/nilla.sqlite3`), `NILLA_SECURE_COOKIE=1` untuk HTTPS, `PYTHON_BIN` untuk launcher Node. Jalankan pertama kali secara lokal untuk membuat owner sebelum mengekspos aplikasi melalui jaringan. Untuk deployment diperlukan HTTPS/reverse proxy, process supervisor, volume database persisten, akses filesystem terbatas, backup terjadwal dan pengujian keamanan terpisah. Python HTTP server bawaan hanya untuk pengembangan/evaluasi.

## Mulai mengisi toko

1. Owner membuat akun manager, kasir, gudang di Pengaturan. Gunakan akun pribadi.
2. Owner menambahkan master produk: SKU, barcode, harga jual, biaya awal, satuan, isi kemasan dan minimum stok. Stok awal nol.
3. Owner menambahkan pemasok. Manager/owner membuat PO dan owner menyetujuinya.
4. Gudang menerima kemasan sesuai fisik; sistem mengonversi ke satuan dasar, menambah stok, mencatat mutasi dan utang.
5. Kasir membuka shift, scan barcode dengan scanner keyboard atau cari nama, pilih member/promo, periksa quote, masukkan uang, konfirmasi tunai dan cetak struk.
6. Kasir menutup shift dengan jumlah uang fisik. Lihat saldo seharusnya dan selisih.
7. Owner meninjau Keuangan, mengisi modal kas serta biaya dan membayar utang sesuai transaksi nyata. Modal laci saat buka shift hanya untuk rekonsiliasi dan tidak menggandakan modal bisnis.

Tidak ada migrasi otomatis dari localStorage prototipe. Data browser lama adalah simulasi dan tidak dianggap catatan operasional.

## Fungsi yang diterapkan

- Login scrypt, sesi HttpOnly dengan kedaluwarsa 8 jam, pembatasan percobaan login, pengecekan origin/header mutasi, RBAC backend untuk empat peran.
- Kasir tidak menerima stok, HPP atau margin pada katalog, quote dan struk; tidak dapat mengakses API persediaan atau keuangan.
- Penjualan tunai atomik: stok, sale/items, ledger kas, poin dan audit. Harga dihitung server, bukan browser. Idempotensi dan serialisasi transaksi mencegah pembayaran ganda serta overselling.
- Buka/tutup shift dan rekonsiliasi. Struk browser, riwayat transaksi milik kasir.
- Produk, pemasok, PO satu SKU, approval owner, penerimaan parsial, konversi kemasan, biaya rata-rata tertimbang, utang dan pembayaran utang terpisah dari HPP.
- Penghitungan fisik memerlukan owner selain pengusul; saldo acuan basi ditolak. Mutasi stok tetap tercatat.
- Member dengan persetujuan penyimpanan telepon, ledger earned/redeemed/refund, kebijakan poin yang dapat diubah owner.
- Promo diskon persen dengan tujuan strategi, periode/hari, kuota, member-only, minimum, cap, approval dan jeda; minimum margin diperiksa pada transaksi sebenarnya.
- Refund penuh barang layak jual pada hari yang sama dan shift asal terbuka, oleh owner saja. Membalik stok, kas dan poin. Ditolak bila poin menjadi negatif atau kas kurang.
- Laporan penjualan, HPP, laba kotor, laba operasional sederhana, kas, biaya, utang dan nilai stok. Filter tanggal, tautan transaksi dan rincian kas. Angka posisi kas/stok adalah posisi saat ini; bukan saldo historis akhir filter.
- Analisis berbasis aturan dan simulator harga dengan asumsi eksplisit. Ini bukan chatbot AI atau forecasting terkalibrasi.

## Pengujian

```sh
python3 -m unittest -v test_backend
node --check app.js
```

14 uji integrasi HTTP menggunakan database sementara: RBAC lintas peran, harga server, idempotensi, rollback transaksi gagal, dua kasir bersamaan, konversi/biaya rata-rata, opname, promo jadwal/kuota/member/margin, poin/refund, shift/ownership, utang/biaya, file sensitif, CSRF/login dan backup-restore. Data operasional tidak disentuh.

Pengujian browser tersedia di `test_browser.cjs`. Memerlukan paket Playwright dan Chromium yang hanya digunakan untuk pengujian. Di lingkungan ini:

```sh
NODE_PATH=/tmp/nilla-browser-check/node_modules PLAYWRIGHT_BROWSERS_PATH=/tmp/nilla-browsers node test_browser.cjs
```

Script menjalankan server sementara pada port 4174, database terpisah dan data uji berlabel. Menjalankan setup owner, login kasir, RBAC, barcode, shift, pembayaran, struk, escaping input HTML, rekonsiliasi, laporan, simulator dan ukuran ponsel. Screenshot disimpan di `test-results/` yang diabaikan Git. Status hasil akhir ada di `VALIDATION.md`.

## Backup dan pemulihan

```sh
python3 backup.py data/nilla.sqlite3 data/backups/nilla-2026-10-25.sqlite3
python3 backup.py data/backups/nilla-2026-10-25.sqlite3 data/restored.sqlite3
NILLA_DB=data/restored.sqlite3 PORT=4175 python3 backend.py
```

Gunakan nama baru setiap snapshot. Perintah tidak menimpa berkas yang sudah ada. SQLite backup API mencakup transaksi yang sudah commit; integrity dan foreign-key check dilakukan. Sesi dibersihkan, login ulang wajib. Cocokkan jumlah transaksi, saldo stok, poin dan kas di hasil restore sebelum mengganti database utama. Hentikan proses aplikasi sebelum mengganti database aktif. Backup memuat data pelanggan dan hash akun: batasi akses, simpan salinan terpisah terenkripsi. Penjadwalan otomatis dan enkripsi backup belum diimplementasikan.

## Yang belum selesai

| Bagian master prompt | Batas implementasi / pekerjaan berikut |
|---|---|
| Keamanan produksi | TLS, MFA, reset password, perubahan/nonaktif akun, rotasi sesi, audit tahan manipulasi filesystem, rate limit terdistribusi, pentest, uji beban belum selesai |
| POS | QRIS/transfer/kartu, pending payment, payment settlement, retur parsial/rusak/lintas tanggal/shift tertutup, pengiriman struk belum tersedia |
| Persediaan | Batch/FEFO, multi lokasi, harga bertingkat, PO multi-item, selisih faktur, retur pemasok, nilai kerugian opname belum lengkap |
| Keuangan | Belum double-entry ledger, pajak, piutang, depresiasi, rekonsiliasi bank atau laporan laba bersih akuntansi; pembulatan HPP per unit bisa menimbulkan selisih valuasi kecil |
| Loyalitas/CRM | Tier dan manfaat yang bisa dikonfigurasi, kadaluwarsa poin, segmentasi RFM, kampanye izin pemasaran belum tersedia |
| Promosi | Saat ini persen untuk seluruh keranjang; belum bundling/Buy X Get Y, scope SKU/kategori, voucher nominal, subsidi pemasok atau pengukuran uplift kausal |
| Business Intelligence | Belum AI eksternal, histori tren lengkap, forecast, smart replenishment, analisis fraud atau kelayakan ekspansi |
| Operasional | Belum publikasi aplikasi, domain publik, installer desktop, backup scheduler atau sinkronisasi offline |

Lihat `DESIGN.md` untuk PRD ringkas, matriks izin, alur, arsitektur dan ERD. `MASTER_PROMPT.md` memuat revisi arahan pengembangan berdasarkan dokumen Anda.
