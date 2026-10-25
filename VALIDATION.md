# Hasil verifikasi — 25 Oktober 2026, Asia/Makassar

## Dijalankan dan lulus

- 14 integration tests HTTP (`python3 -m unittest -v test_backend`), database sementara per test. Semua selesai, tidak ada skipped.
- Browser Chromium headless: owner bootstrap, login kasir, hak menu/API, scanner keyboard, membuka shift, quote, pembayaran tunai, kembalian Rp10.000 untuk tender Rp20.000 dan total Rp10.000, struk tersimpan, member dengan payload HTML tampil aman, rekonsiliasi laci, laporan owner, simulator dan viewport 390 px tanpa overflow halaman.
- Browser tidak melaporkan JavaScript page errors selama alur yang diuji.
- Backup SQLite, integrity/foreign-key check, restore ke database baru, login ulang, lalu verifikasi stok, poin, dan penjualan melalui API.
- Pemeriksaan sintaks Python dan JavaScript serta `git diff --check`.

## Perbaikan dibanding prototipe

1. localStorage bukan lagi sumber kebenaran; transaksi disimpan server.
2. Angka omzet, pertumbuhan, jumlah member dan target statis dihapus.
3. Stok/HPP tidak dikirim ke kasir. Hak akses diuji lewat API langsung.
4. Pembayaran harus melewati quote, uang diterima dan konfirmasi. Stok, kas dan poin commit bersama.
5. Dua pembeli stok terakhir menghasilkan satu sukses, satu ditolak; stok tidak negatif.
6. Pengulangan permintaan identik tidak membuat transaksi kedua. Harga manipulasi browser tidak digunakan.
7. Promo memeriksa tanggal, hari, member, minimum, cap, kuota, approval dan margin.
8. Poin memiliki ledger dan refund reversal; bukan hanya saldo akhir.
9. Opname tidak langsung mengubah stok. Owner tidak dapat menyetujui hitungannya sendiri; hitungan basi ditolak.
10. Server hanya melayani aset publik yang didaftarkan; source, database dan `.git` tidak bisa diunduh.
11. Dialog native menutup dan menyembunyikan modal dengan benar; input dinamis di-escape; font eksternal dihapus.

## Batas bukti

Ini bukan pentest atau sertifikasi kesiapan produksi. Tidak menguji perangkat scanner/printer fisik, gateway pembayaran, Windows, beban besar, jaringan putus, multi-cabang, skenario seluruh fitur master prompt atau integrasi AI. Tes browser memakai data uji di database sementara, bukan data toko. Screenshot di test-results menggambarkan fixture pengujian.

Spesifikasi tahap berikut dan batas fungsi ada di README. Semua kemampuan yang belum diimplementasikan tetap belum teruji; tidak dianggap lulus hanya karena ada dalam dokumen desain.
