"""Local retail API. Integer Rupiah, SQLite transactions, server-side permissions."""
import hashlib, hmac, json, os, secrets, sqlite3, time
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
DB = Path(os.environ.get('NILLA_DB', ROOT / 'data/nilla.sqlite3'))
TZ = ZoneInfo('Asia/Makassar')
ROLES = ('owner','manager','cashier','warehouse')
OPS = ('owner','manager')
POS = ('owner','manager','cashier')
STOCK = ('owner','manager','warehouse')
def now(): return datetime.now(TZ).isoformat(timespec='seconds')
def day(): return datetime.now(TZ).date().isoformat()
def hashpw(password,salt): return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def connect():
    db=sqlite3.connect(DB,timeout=15); db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON'); return db
def rows(db,sql,args=()): return [dict(r) for r in db.execute(sql,args)]
def one(db,sql,args=()):
    r=db.execute(sql,args).fetchone(); return dict(r) if r else None
class Invalid(Exception):
    def __init__(self,message,status=400): self.message,self.status=message,status
def require(ok,message,status=400):
    if not ok: raise Invalid(message,status)
def allow(user,roles): require(user['role'] in roles,'Akses ditolak untuk peran ini.',403)
def integer(v,low=0,high=1000000000000):
    require(type(v) is int and low<=v<=high,'Angka harus bilangan bulat dalam batas valid.'); return v
def label(v,limit=150):
    require(isinstance(v,str) and 0<len(v.strip())<=limit,'Teks wajib diisi dan tidak boleh terlalu panjang.'); return v.strip()
def audit(db,u,action,detail): db.execute('INSERT INTO audit(at,user_id,action,detail) VALUES(?,?,?,?)',(now(),u['id'],action,json.dumps(detail,ensure_ascii=False)))
def move(db,u,pid,qty,kind,ref): db.execute('INSERT INTO movements(at,user_id,product_id,qty,kind,ref) VALUES(?,?,?,?,?,?)',(now(),u['id'],pid,qty,kind,str(ref)))
def cash(db,u,amount,kind,ref): db.execute('INSERT INTO cash(at,user_id,amount,kind,ref) VALUES(?,?,?,?,?)',(now(),u['id'],amount,kind,str(ref)))
def balance(db): return db.execute('SELECT COALESCE(SUM(amount),0) FROM cash').fetchone()[0]
def points(db,mid): return db.execute('SELECT COALESCE(SUM(delta),0) FROM loyalty WHERE member_id=?',(mid,)).fetchone()[0]
def settings(db): return one(db,'SELECT * FROM settings WHERE id=1')
def initialize():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,role TEXT NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(ip TEXT PRIMARY KEY,count INTEGER NOT NULL,until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,sku TEXT UNIQUE NOT NULL,barcode TEXT UNIQUE NOT NULL,name TEXT NOT NULL,category TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>0),cost INTEGER NOT NULL CHECK(cost>=0),stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0),minimum INTEGER NOT NULL DEFAULT 5,unit TEXT NOT NULL DEFAULT 'pcs',conversion INTEGER NOT NULL DEFAULT 1 CHECK(conversion>0));
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,contact TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT UNIQUE,consent INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS promos(id INTEGER PRIMARY KEY,code TEXT UNIQUE NOT NULL,title TEXT NOT NULL,strategy TEXT NOT NULL,percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 50),minimum INTEGER NOT NULL,cap INTEGER NOT NULL,starts TEXT NOT NULL,ends TEXT NOT NULL,weekdays TEXT NOT NULL,member_only INTEGER NOT NULL,quota INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',creator INTEGER REFERENCES users,approver INTEGER REFERENCES users);
CREATE TABLE IF NOT EXISTS shifts(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users,opened TEXT NOT NULL,opening INTEGER NOT NULL,closed TEXT,counted INTEGER,expected INTEGER,difference INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS open_shift ON shifts(user_id) WHERE closed IS NULL;
CREATE TABLE IF NOT EXISTS sales(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,at TEXT NOT NULL,user_id INTEGER REFERENCES users,shift_id INTEGER REFERENCES shifts,member_id INTEGER REFERENCES members,promo_id INTEGER REFERENCES promos,subtotal INTEGER NOT NULL,discount INTEGER NOT NULL,total INTEGER NOT NULL,cost INTEGER NOT NULL,tender INTEGER NOT NULL,change_due INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'paid',refunded TEXT,refund_reason TEXT);
CREATE TABLE IF NOT EXISTS sale_items(sale_id TEXT REFERENCES sales,product_id INTEGER REFERENCES products,name TEXT NOT NULL,qty INTEGER NOT NULL,price INTEGER NOT NULL,cost INTEGER NOT NULL,PRIMARY KEY(sale_id,product_id));
CREATE TABLE IF NOT EXISTS loyalty(id INTEGER PRIMARY KEY,at TEXT NOT NULL,member_id INTEGER REFERENCES members,sale_id TEXT REFERENCES sales,delta INTEGER NOT NULL,kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY,at TEXT NOT NULL,product_id INTEGER REFERENCES products,qty INTEGER NOT NULL,kind TEXT NOT NULL,ref TEXT NOT NULL,user_id INTEGER REFERENCES users);
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY,supplier_id INTEGER REFERENCES suppliers,product_id INTEGER REFERENCES products,qty INTEGER NOT NULL,cost INTEGER NOT NULL,conversion INTEGER NOT NULL,received INTEGER NOT NULL DEFAULT 0,paid INTEGER NOT NULL DEFAULT 0,due TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',creator INTEGER REFERENCES users,approver INTEGER REFERENCES users);
CREATE TABLE IF NOT EXISTS counts(id INTEGER PRIMARY KEY,product_id INTEGER REFERENCES products,baseline INTEGER NOT NULL,physical INTEGER NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',creator INTEGER REFERENCES users,approver INTEGER REFERENCES users);
CREATE TABLE IF NOT EXISTS cash(id INTEGER PRIMARY KEY,at TEXT NOT NULL,amount INTEGER NOT NULL,kind TEXT NOT NULL,ref TEXT NOT NULL,user_id INTEGER REFERENCES users);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,user_id INTEGER REFERENCES users,action TEXT NOT NULL,detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),earn_step INTEGER NOT NULL DEFAULT 10000,point_value INTEGER NOT NULL DEFAULT 100,min_margin INTEGER NOT NULL DEFAULT 5,reserve INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO settings(id) VALUES(1);
''')

def quote(db,u,d):
    allow(u,POS); lines=d.get('items'); require(isinstance(lines,list) and 0<len(lines)<=200,'Keranjang kosong atau terlalu besar.')
    combined={}
    for line in lines:
        pid=integer(line.get('id'),1); qty=integer(line.get('qty'),1,100000); combined[pid]=combined.get(pid,0)+qty
    items=[]; subtotal=cost=0
    for pid,qty in combined.items():
        p=one(db,'SELECT * FROM products WHERE id=?',(pid,)); require(p and p['stock']>=qty,'Produk tidak tersedia untuk jumlah pembelian ini.')
        items.append(dict(id=pid,name=p['name'],qty=qty,price=p['price'],cost=p['cost'])); subtotal+=p['price']*qty; cost+=p['cost']*qty
    mid=d.get('member_id') or None
    if mid: require(one(db,'SELECT id FROM members WHERE id=?',(integer(mid,1),)),'Member tidak ditemukan.')
    promo=None; discount=0; code=d.get('promo','').strip().upper()
    if code:
        promo=one(db,'SELECT * FROM promos WHERE code=?',(code,)); require(promo and promo['status']=='approved','Promo belum disetujui atau tidak tersedia.')
        require(promo['starts']<=day()<=promo['ends'],'Promo di luar periode aktif.')
        require(str(datetime.now(TZ).weekday()) in promo['weekdays'].split(','),'Promo tidak berlaku hari ini.')
        require(not promo['member_only'] or mid,'Promo khusus member.'); require(subtotal>=promo['minimum'],'Minimum belanja promo belum terpenuhi.')
        require(db.execute('SELECT COUNT(*) FROM sales WHERE promo_id=?',(promo['id'],)).fetchone()[0]<promo['quota'],'Kuota promo habis.')
        discount=min((subtotal*promo['percent']+50)//100,promo['cap'])
    cfg=settings(db); redeem=integer(d.get('redeem',0)); require(not redeem or mid,'Penukaran poin memerlukan member.')
    require(not redeem or redeem<=points(db,mid),'Saldo poin tidak cukup.'); discount+=redeem*cfg['point_value']; total=subtotal-discount
    require(total>0,'Total setelah diskon harus lebih dari nol.')
    require((total-cost)*100>=total*cfg['min_margin'],'Transaksi ditolak: margin setelah diskon di bawah batas owner.')
    return dict(items=items,subtotal=subtotal,discount=discount,total=total,cost=cost,member_id=mid,promo_id=promo['id'] if promo else None,redeemed=redeem,earned=total//cfg['earn_step'] if mid else 0)
def public_quote(q): return {k:([{a:b for a,b in i.items() if a!='cost'} for i in v] if k=='items' else v) for k,v in q.items() if k!='cost'}

def api(db,u,method,path,d,query):
    role=u['role']
    if path=='/api/me': return dict(user={k:u[k] for k in ('id','name','role')},settings=settings(db) if role=='owner' else {},timezone='Asia/Makassar')
    if path=='/api/logout': db.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],)); return {'ok':True}
    if path=='/api/products':
        if method=='GET':
            fields='*' if role in OPS else ('id,sku,barcode,name,category,price,stock,minimum,unit,conversion' if role=='warehouse' else 'id,sku,barcode,name,category,price,unit')
            return rows(db,f'SELECT {fields} FROM products ORDER BY name')
        allow(u,('owner',)); db.execute('INSERT INTO products(sku,barcode,name,category,price,cost,minimum,unit,conversion) VALUES(?,?,?,?,?,?,?,?,?)',(label(d.get('sku')),label(d.get('barcode')),label(d.get('name')),label(d.get('category')),integer(d.get('price'),1),integer(d.get('cost')),integer(d.get('minimum',5)),label(d.get('unit','pcs')),integer(d.get('conversion',1),1)))
        audit(db,u,'product.create',{'sku':d['sku']}); return {'ok':True}
    if path=='/api/users':
        allow(u,('owner',))
        if method=='GET': return rows(db,'SELECT id,name,role,active FROM users')
        name=label(d.get('name'),60); password=label(d.get('password'),128); role_=d.get('role'); require(len(password)>=12 and role_ in ROLES,'Kata sandi minimal 12 karakter dan peran harus valid.'); salt=secrets.token_hex(16)
        db.execute('INSERT INTO users(name,role,salt,hash) VALUES(?,?,?,?)',(name,role_,salt,hashpw(password,salt))); audit(db,u,'user.create',{'name':name,'role':role_}); return {'ok':True}
    if path=='/api/suppliers':
        allow(u,STOCK)
        if method=='GET': return rows(db,'SELECT * FROM suppliers')
        allow(u,('owner',)); db.execute('INSERT INTO suppliers(name,contact) VALUES(?,?)',(label(d.get('name')),label(d.get('contact')))); audit(db,u,'supplier.create',{'name':d['name']}); return {'ok':True}
    if path=='/api/members':
        allow(u,POS)
        if method=='GET': return rows(db,"SELECT m.*,COALESCE((SELECT SUM(delta) FROM loyalty WHERE member_id=m.id),0) points,(SELECT COUNT(*) FROM sales WHERE member_id=m.id AND status='paid') visits FROM members m")
        phone=d.get('phone','').strip(); consent=bool(d.get('consent')); require(not phone or consent,'Persetujuan pelanggan diperlukan untuk menyimpan nomor telepon.'); require(len(phone)<=25,'Nomor terlalu panjang.')
        db.execute('INSERT INTO members(name,phone,consent,created) VALUES(?,?,?,?)',(label(d.get('name')),phone or None,int(consent),now())); audit(db,u,'member.create',{}); return {'ok':True}
    if path=='/api/loyalty':
        allow(u,POS); return rows(db,'SELECT * FROM loyalty WHERE member_id=? ORDER BY id DESC',(integer(int(query.get('member',['0'])[0]),1),))
    if path=='/api/promos':
        allow(u,POS)
        if method=='GET': return rows(db,"SELECT id,code,title,strategy,percent,minimum,cap,starts,ends,weekdays,member_only,quota,status FROM promos"+(" WHERE status='approved'" if role=='cashier' else ''))
        allow(u,OPS); starts=label(d.get('starts'),10); ends=label(d.get('ends'),10); require(datetime.fromisoformat(starts)<=datetime.fromisoformat(ends),'Periode tidak valid.')
        weekdays=label(d.get('weekdays','0,1,2,3,4,5,6'),13); require(all(len(x)==1 and x in '0123456' for x in weekdays.split(',')),'Hari tidak valid.')
        db.execute('INSERT INTO promos(code,title,strategy,percent,minimum,cap,starts,ends,weekdays,member_only,quota,creator) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(label(d.get('code'),30).upper(),label(d.get('title')),label(d.get('strategy')),integer(d.get('percent'),1,50),integer(d.get('minimum')),integer(d.get('cap'),1),starts,ends,weekdays,int(bool(d.get('member_only'))),integer(d.get('quota'),1),u['id']))
        audit(db,u,'promo.propose',{'code':d['code']}); return {'ok':True}
    if path=='/api/promos/approve':
        allow(u,('owner',)); pid=integer(d.get('id'),1); require(db.execute("UPDATE promos SET status='approved',approver=? WHERE id=? AND status='pending'",(u['id'],pid)).rowcount,'Promo tidak menunggu persetujuan.'); audit(db,u,'promo.approve',{'id':pid}); return {'ok':True}
    if path=='/api/promos/pause':
        allow(u,OPS); pid=integer(d.get('id'),1); db.execute("UPDATE promos SET status='paused' WHERE id=?",(pid,)); audit(db,u,'promo.pause',{'id':pid}); return {'ok':True}
    if path=='/api/shifts':
        allow(u,POS)
        if method=='GET': return rows(db,'SELECT * FROM shifts WHERE user_id=? ORDER BY id DESC',(u['id'],))
        opening=integer(d.get('opening')); db.execute('INSERT INTO shifts(user_id,opened,opening) VALUES(?,?,?)',(u['id'],now(),opening)); audit(db,u,'shift.open',{'opening':opening}); return {'ok':True}
    if path=='/api/shifts/close':
        allow(u,POS); shift=one(db,'SELECT * FROM shifts WHERE user_id=? AND closed IS NULL',(u['id'],)); require(shift,'Tidak ada shift aktif.')
        expected=shift['opening']+db.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE shift_id=? AND status='paid'",(shift['id'],)).fetchone()[0]; counted=integer(d.get('counted'))
        db.execute('UPDATE shifts SET closed=?,counted=?,expected=?,difference=? WHERE id=?',(now(),counted,expected,counted-expected,shift['id'])); audit(db,u,'shift.close',{'id':shift['id'],'difference':counted-expected}); return {'expected':expected,'difference':counted-expected}
    if path=='/api/quote': return public_quote(quote(db,u,d))
    if path=='/api/sales' and method=='POST':
        allow(u,POS); key=label(d.get('key'),100); digest=hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest(); previous=one(db,'SELECT * FROM sales WHERE request_key=?',(key,))
        if previous:
            require(previous['user_id']==u['id'] and previous['request_hash']==digest,'Kunci transaksi sudah dipakai untuk permintaan berbeda.',409)
            return {k:v for k,v in previous.items() if k not in ('cost','request_key','request_hash')}
        shift=one(db,'SELECT * FROM shifts WHERE user_id=? AND closed IS NULL',(u['id'],)); require(shift,'Buka shift sebelum berjualan.')
        q=quote(db,u,d); tender=integer(d.get('tender')); require(tender>=q['total'],'Uang diterima kurang dari total.'); sid='NDM-'+secrets.token_hex(6).upper()
        db.execute('INSERT INTO sales(id,request_key,request_hash,at,user_id,shift_id,member_id,promo_id,subtotal,discount,total,cost,tender,change_due) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,key,digest,now(),u['id'],shift['id'],q['member_id'],q['promo_id'],q['subtotal'],q['discount'],q['total'],q['cost'],tender,tender-q['total']))
        for i in q['items']:
            db.execute('INSERT INTO sale_items VALUES(?,?,?,?,?,?)',(sid,i['id'],i['name'],i['qty'],i['price'],i['cost'])); db.execute('UPDATE products SET stock=stock-? WHERE id=?',(i['qty'],i['id'])); move(db,u,i['id'],-i['qty'],'sale',sid)
        if q['member_id']:
            for delta,kind in ((-q['redeemed'],'redeem'),(q['earned'],'earn')):
                if delta: db.execute('INSERT INTO loyalty(at,member_id,sale_id,delta,kind) VALUES(?,?,?,?,?)',(now(),q['member_id'],sid,delta,kind))
        cash(db,u,q['total'],'sale',sid); audit(db,u,'sale.paid',{'id':sid,'total':q['total']}); return dict(id=sid,**public_quote(q),tender=tender,change_due=tender-q['total'])
    if path=='/api/sales':
        allow(u,POS); return rows(db,'SELECT id,at,user_id,member_id,subtotal,discount,total,tender,change_due,status FROM sales'+(' WHERE user_id=?' if role=='cashier' else '')+' ORDER BY at DESC',(u['id'],) if role=='cashier' else ())
    if path=='/api/receipt':
        allow(u,POS); sid=query.get('id',[''])[0]; sale=one(db,'SELECT * FROM sales WHERE id=?',(sid,)); require(sale,'Transaksi tidak ditemukan.',404); require(role in OPS or sale['user_id']==u['id'],'Akses ditolak.',403)
        result={k:v for k,v in sale.items() if k not in ('cost','request_key','request_hash')}; result['items']=rows(db,'SELECT name,qty,price FROM sale_items WHERE sale_id=?',(sid,)); return result
    if path=='/api/refund':
        allow(u,('owner',)); sid=label(d.get('id')); reason=label(d.get('reason')); sale=one(db,'SELECT s.*,h.closed FROM sales s JOIN shifts h ON h.id=s.shift_id WHERE s.id=?',(sid,)); require(sale and sale['status']=='paid','Penjualan tidak tersedia untuk refund.'); require(not sale['closed'],'Refund shift tertutup belum didukung; perlu prosedur koreksi kas terpisah.')
        require(sale['at'][:10]==day(),'Refund lintas tanggal belum didukung; perlu jurnal koreksi periode terpisah.')
        delta=db.execute('SELECT COALESCE(SUM(delta),0) FROM loyalty WHERE sale_id=?',(sid,)).fetchone()[0]; require(not sale['member_id'] or points(db,sale['member_id'])-delta>=0,'Poin sudah digunakan; selesaikan poin sebelum refund.')
        require(balance(db)>=sale['total'],'Saldo kas tidak cukup untuk refund.')
        for i in rows(db,'SELECT * FROM sale_items WHERE sale_id=?',(sid,)):
            p=one(db,'SELECT * FROM products WHERE id=?',(i['product_id'],)); stock=p['stock']+i['qty']; cost=(p['stock']*p['cost']+i['qty']*i['cost']+stock//2)//stock
            db.execute('UPDATE products SET stock=?,cost=? WHERE id=?',(stock,cost,p['id'])); move(db,u,p['id'],i['qty'],'refund',sid)
        if sale['member_id']: db.execute('INSERT INTO loyalty(at,member_id,sale_id,delta,kind) VALUES(?,?,?,?,?)',(now(),sale['member_id'],sid,-delta,'refund'))
        db.execute("UPDATE sales SET status='refunded',refunded=?,refund_reason=? WHERE id=?",(now(),reason,sid)); cash(db,u,-sale['total'],'refund',sid); audit(db,u,'sale.refund',{'id':sid,'reason':reason}); return {'ok':True}
    if path=='/api/inventory':
        allow(u,STOCK); return rows(db,'SELECT m.*,p.name FROM movements m JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 500')
    if path=='/api/counts':
        allow(u,STOCK)
        if method=='GET': return rows(db,'SELECT c.*,p.name FROM counts c JOIN products p ON p.id=c.product_id ORDER BY c.id DESC')
        pid=integer(d.get('product_id'),1); p=one(db,'SELECT * FROM products WHERE id=?',(pid,)); require(p,'Produk tidak ditemukan.'); db.execute('INSERT INTO counts(product_id,baseline,physical,reason,creator) VALUES(?,?,?,?,?)',(pid,p['stock'],integer(d.get('physical')),label(d.get('reason')),u['id'])); audit(db,u,'count.propose',{'product_id':pid}); return {'ok':True}
    if path=='/api/counts/approve':
        allow(u,('owner',)); c=one(db,"SELECT * FROM counts WHERE id=? AND status='pending'",(integer(d.get('id'),1),)); require(c,'Usulan tidak tersedia.'); require(c['creator']!=u['id'],'Pengusul tidak boleh menyetujui hitungan sendiri.')
        p=one(db,'SELECT * FROM products WHERE id=?',(c['product_id'],)); require(p['stock']==c['baseline'],'Stok berubah sejak hitungan; lakukan hitungan baru.',409); db.execute('UPDATE products SET stock=? WHERE id=?',(c['physical'],p['id'])); move(db,u,p['id'],c['physical']-p['stock'],'count',c['id']); db.execute("UPDATE counts SET status='approved',approver=? WHERE id=?",(u['id'],c['id'])); audit(db,u,'count.approve',{'id':c['id'],'reason':c['reason']}); return {'ok':True}
    if path=='/api/purchases':
        allow(u,STOCK)
        if method=='GET':
            fields='p.*' if role in OPS else 'p.id,p.product_id,p.supplier_id,p.qty,p.conversion,p.received,p.status,p.due'
            return rows(db,f'SELECT {fields},s.name supplier,r.name product FROM purchases p JOIN suppliers s ON s.id=p.supplier_id JOIN products r ON r.id=p.product_id ORDER BY p.id DESC')
        allow(u,OPS); pid=integer(d.get('product_id'),1); p=one(db,'SELECT * FROM products WHERE id=?',(pid,)); require(p,'Produk tidak ditemukan.'); due=label(d.get('due'),10); datetime.fromisoformat(due)
        db.execute('INSERT INTO purchases(supplier_id,product_id,qty,cost,conversion,due,creator) VALUES(?,?,?,?,?,?,?)',(integer(d.get('supplier_id'),1),pid,integer(d.get('qty'),1),integer(d.get('cost'),1),p['conversion'],due,u['id'])); audit(db,u,'purchase.propose',{'product_id':pid}); return {'ok':True}
    if path=='/api/purchases/approve':
        allow(u,('owner',)); pid=integer(d.get('id'),1); require(db.execute("UPDATE purchases SET status='approved',approver=? WHERE id=? AND status='pending'",(u['id'],pid)).rowcount,'PO tidak menunggu persetujuan.'); audit(db,u,'purchase.approve',{'id':pid}); return {'ok':True}
    if path=='/api/purchases/receive':
        allow(u,STOCK); po=one(db,"SELECT * FROM purchases WHERE id=? AND status='approved'",(integer(d.get('id'),1),)); require(po,'PO belum disetujui.'); qty=integer(d.get('qty'),1); require(qty<=po['qty']-po['received'],'Penerimaan melebihi sisa PO.')
        p=one(db,'SELECT * FROM products WHERE id=?',(po['product_id'],)); units=qty*po['conversion']; stock=p['stock']+units; cost=(p['cost']*p['stock']+po['cost']*units+stock//2)//stock
        db.execute('UPDATE products SET stock=?,cost=? WHERE id=?',(stock,cost,p['id'])); db.execute('UPDATE purchases SET received=received+? WHERE id=?',(qty,po['id'])); move(db,u,p['id'],units,'receipt',po['id']); audit(db,u,'purchase.receive',{'id':po['id'],'packs':qty}); return {'ok':True}
    if path=='/api/purchases/pay':
        allow(u,('owner',)); po=one(db,'SELECT * FROM purchases WHERE id=?',(integer(d.get('id'),1),)); require(po,'PO tidak ditemukan.'); amount=integer(d.get('amount'),1); require(amount<=po['received']*po['conversion']*po['cost']-po['paid'],'Pembayaran melebihi utang diterima.'); require(amount<=balance(db),'Saldo kas tidak cukup.')
        db.execute('UPDATE purchases SET paid=paid+? WHERE id=?',(amount,po['id'])); cash(db,u,-amount,'supplier_payment',po['id']); audit(db,u,'purchase.pay',{'id':po['id'],'amount':amount}); return {'ok':True}
    if path=='/api/cash':
        allow(u,('owner',)); kind=d.get('kind'); require(kind in ('capital','expense'),'Jenis kas tidak valid.'); amount=integer(d.get('amount'),1); reason=label(d.get('reason'))
        if kind=='expense': require(amount<=balance(db),'Saldo kas tidak cukup.')
        cash(db,u,amount if kind=='capital' else -amount,kind,reason); audit(db,u,'cash.'+kind,{'amount':amount,'reason':reason}); return {'ok':True}
    if path=='/api/report':
        allow(u,OPS); start=query.get('start',[day()])[0]; end=query.get('end',[day()])[0]; require(start<=end,'Rentang tanggal tidak valid.')
        sales=rows(db,"SELECT id,at,total,cost,discount,promo_id,user_id FROM sales WHERE status='paid' AND substr(at,1,10) BETWEEN ? AND ?",(start,end))
        r=dict(start=start,end=end,transactions=len(sales),revenue=sum(s['total'] for s in sales),discount=sum(s['discount'] for s in sales),sales=[{k:v for k,v in s.items() if k!='cost'} for s in sales],low_stock=rows(db,'SELECT id,name,stock,minimum FROM products WHERE stock<=minimum'))
        if role=='owner':
            r['hpp']=sum(s['cost'] for s in sales); r['gross_profit']=r['revenue']-r['hpp']; r['cash_entries']=rows(db,'SELECT * FROM cash WHERE substr(at,1,10) BETWEEN ? AND ? ORDER BY id DESC',(start,end)); r['expenses']=-sum(c['amount'] for c in r['cash_entries'] if c['kind']=='expense'); r['operating_profit']=r['gross_profit']-r['expenses']; r['cash']=balance(db); r['inventory_value']=db.execute('SELECT COALESCE(SUM(stock*cost),0) FROM products').fetchone()[0]
            r['payables']=rows(db,'SELECT id,due,received*conversion*cost-paid balance FROM purchases WHERE received*conversion*cost>paid'); r['reserve']=settings(db)['reserve']; r['projected_after_debts']=r['cash']-sum(p['balance'] for p in r['payables']); r['risk']='Kritis' if r['projected_after_debts']<0 else ('Di bawah cadangan' if r['projected_after_debts']<r['reserve'] else 'Di atas cadangan')
        return r
    if path=='/api/audit':
        allow(u,('owner',)); return rows(db,'SELECT a.*,u.name actor FROM audit a JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 500')
    if path=='/api/settings':
        allow(u,('owner',)); db.execute('UPDATE settings SET earn_step=?,point_value=?,min_margin=?,reserve=? WHERE id=1',(integer(d.get('earn_step'),1),integer(d.get('point_value'),1),integer(d.get('min_margin'),0,90),integer(d.get('reserve')))); audit(db,u,'settings.update',d); return {'ok':True}
    raise Invalid('Endpoint tidak ditemukan.',404)

GETS={'me','products','users','suppliers','members','loyalty','promos','shifts','sales','receipt','inventory','counts','purchases','report','audit'}
POSTS={'logout','products','users','suppliers','members','promos','promos/approve','promos/pause','shifts','shifts/close','quote','sales','refund','counts','counts/approve','purchases','purchases/approve','purchases/receive','purchases/pay','cash','settings'}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def send(self,status,content,kind='application/json',cookie=None):
        raw=json.dumps(content,ensure_ascii=False).encode() if kind=='application/json' else content
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items(): self.send_header(k,v)
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def handle_request(self,method):
        parsed=urlparse(self.path); path=parsed.path
        if not path.startswith('/api/'):
            assets={'/':'index.html','/index.html':'index.html','/styles.css':'styles.css','/app.js':'app.js'}
            if method!='GET' or path not in assets: return self.send(404,{'error':'Tidak ditemukan.'})
            file=ROOT/assets[path]; return self.send(200,file.read_bytes(),{'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'application/javascript; charset=utf-8'}[file.suffix])
        db=connect()
        try:
            d={}
            if method=='POST':
                require(self.headers.get('X-Nilla-Request')=='1','Header permintaan diperlukan.',403); origin=self.headers.get('Origin'); require(not origin or urlparse(origin).netloc==self.headers.get('Host'),'Origin tidak diizinkan.',403)
                size=int(self.headers.get('Content-Length','0')); require(0<size<=65536,'Ukuran permintaan tidak valid.'); d=json.loads(self.rfile.read(size)); require(isinstance(d,dict),'Objek JSON diperlukan.')
            db.execute('BEGIN IMMEDIATE' if method=='POST' else 'BEGIN')
            if path=='/api/status' and method=='GET':
                result={'setup_required':not db.execute('SELECT 1 FROM users LIMIT 1').fetchone()}; db.commit(); return self.send(200,result)
            if path=='/api/setup' and method=='POST':
                require(not db.execute('SELECT 1 FROM users LIMIT 1').fetchone(),'Owner sudah dibuat.',409); name=label(d.get('name'),60); password=label(d.get('password'),128); require(len(password)>=12,'Kata sandi minimal 12 karakter.'); salt=secrets.token_hex(16)
                db.execute("INSERT INTO users(name,role,salt,hash) VALUES(?,'owner',?,?)",(name,salt,hashpw(password,salt))); audit(db,{'id':1},'owner.setup',{}); db.commit(); return self.send(201,{'ok':True})
            if path=='/api/login' and method=='POST':
                ip=self.client_address[0]; a=one(db,'SELECT * FROM attempts WHERE ip=?',(ip,)); require(not a or a['count']<5 or time.time()>a['until'],'Terlalu banyak percobaan. Tunggu 5 menit.',429)
                u=one(db,'SELECT * FROM users WHERE name=? AND active=1',(label(d.get('name'),60),)); password=label(d.get('password'),128)
                if not u or not hmac.compare_digest(u['hash'],hashpw(password,u['salt'])):
                    count=a['count']+1 if a and time.time()<a['until'] else 1; db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(ip,count,time.time()+300)); db.commit(); raise Invalid('Nama akun atau kata sandi salah.',401)
                db.execute('DELETE FROM attempts WHERE ip=?',(ip,)); token=secrets.token_urlsafe(32); db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],time.time()+28800)); audit(db,u,'login',{}); db.commit(); secure='; Secure' if os.environ.get('NILLA_SECURE_COOKIE')=='1' else ''
                return self.send(200,{'ok':True},cookie=f'nilla={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}')
            cookies=dict(x.strip().split('=',1) for x in self.headers.get('Cookie','').split(';') if '=' in x)
            u=one(db,'SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1',(hashlib.sha256(cookies.get('nilla','').encode()).hexdigest(),time.time())); require(u,'Silakan login.',401)
            require(path[5:] in (GETS if method=='GET' else POSTS),'Metode atau endpoint tidak tersedia.',405)
            result=api(db,u,method,path,d,parse_qs(parsed.query)); db.commit(); self.send(200,result)
        except Invalid as error: db.rollback(); self.send(error.status,{'error':error.message})
        except (ValueError,TypeError,KeyError,AttributeError,sqlite3.IntegrityError): db.rollback(); self.send(400,{'error':'Data tidak valid, duplikat, atau bertentangan dengan catatan tersimpan.'})
        except Exception: db.rollback(); self.send(500,{'error':'Operasi gagal. Seluruh perubahan dibatalkan.'})
        finally: db.close()

if __name__=='__main__':
    initialize(); port=int(os.environ.get('PORT','4173')); host=os.environ.get('HOST','127.0.0.1'); print(f'Nilla Daily Mart: {host}:{port}',flush=True); ThreadingHTTPServer((host,port),Handler).serve_forever()
