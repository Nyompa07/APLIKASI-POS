"""HTTP acceptance tests; all fixtures live in temporary databases."""
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import backend as b

class RetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); b.DB=Path(cls.temp.name)/'test.sqlite3'; b.initialize()
        cls.server=b.ThreadingHTTPServer(('127.0.0.1',0),b.Handler); cls.port=cls.server.server_port
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        # Windows keeps an SQLite file locked until every request thread exits.
        cls.server.shutdown(); cls.thread.join(timeout=10); cls.server.server_close()
        last=None
        for _ in range(20):
            try:
                cls.temp.cleanup(); return
            except PermissionError as error:
                last=error; time.sleep(.1)
        raise last
    def req(self,path,data=None,cookie=None,method=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port); headers={'Content-Type':'application/json','X-Nilla-Request':'1'}
        if cookie: headers['Cookie']=cookie
        c.request(method or ('POST' if data is not None else 'GET'),'/api/'+path,json.dumps(data) if data is not None else None,headers)
        r=c.getresponse(); body=json.loads(r.read()); token=r.getheader('Set-Cookie'); status=r.status; c.close(); return status,body,token
    def ok(self,path,data=None,who='owner'):
        status,result,_=self.req(path,data,self.cookies.get(who)); self.assertEqual(status,200,(path,result)); return result
    def setUp(self):
        # Fresh data per test; server only processes each test's requests.
        db=b.connect()
        try:
            db.execute('PRAGMA foreign_keys=OFF')
            for table in ('sessions','attempts','audit','cash','movements','loyalty','sale_items','sales','shifts','counts','purchases','promos','members','suppliers','products','users'): db.execute('DELETE FROM '+table)
            db.execute('UPDATE settings SET earn_step=10000,point_value=100,min_margin=5,reserve=0')
            db.commit()
        finally:
            db.close()
        self.password=secrets.token_urlsafe(18); self.cookies={}
        self.assertEqual(self.req('setup',{'name':'owner','password':self.password})[0],201)
        self.cookies['owner']=self.req('login',{'name':'owner','password':self.password})[2]
        for role in ('manager','cashier','warehouse'):
            self.ok('users',{'name':role,'password':self.password,'role':role})
            self.cookies[role]=self.req('login',{'name':role,'password':self.password})[2]
        self.ok('products',{'sku':'SKU1','barcode':'12345','name':'Produk uji','category':'Uji','price':10000,'cost':6000,'conversion':12})
        self.ok('suppliers',{'name':'Pemasok uji','contact':'Kontak uji'})
        self.ok('purchases',{'product_id':1,'supplier_id':1,'qty':2,'cost':6000,'due':b.day()})
        self.ok('purchases/approve',{'id':1}); self.ok('purchases/receive',{'id':1,'qty':2},'warehouse')
        self.ok('shifts',{'opening':100000},'cashier'); self.ok('shifts',{'opening':0},'manager')
        self.ok('members',{'name':'Member uji','phone':'','consent':False},'cashier')
    def sale(self,qty=1,**kw): return dict(items=[{'id':1,'qty':qty}],key=secrets.token_hex(12),tender=qty*10000,**kw)
    def test_rbac_and_no_cost_or_stock_leak(self):
        catalog=self.ok('products',who='cashier'); self.assertNotIn('stock',catalog[0]); self.assertNotIn('cost',catalog[0])
        q=self.ok('quote',self.sale(),'cashier'); self.assertNotIn('cost',q); self.assertNotIn('cost',q['items'][0])
        for path in ('inventory','counts','purchases','report','audit','users','suppliers'):
            self.assertEqual(self.req(path,cookie=self.cookies['cashier'])[0],403,path)
        self.assertEqual(self.req('sales',self.sale(),self.cookies['warehouse'])[0],403)
        self.assertNotIn('cost',self.ok('products',who='warehouse')[0]); self.assertNotIn('cost',self.ok('purchases',who='warehouse')[0])
        self.assertNotIn('cash',self.ok('report',who='manager')); self.assertEqual(self.req('audit',cookie=self.cookies['manager'])[0],403)
    def test_sale_atomic_idempotent_and_server_prices(self):
        d=self.sale(2,member_id=1); d['items'][0]['price']=1
        first=self.ok('sales',d,'cashier'); second=self.ok('sales',d,'cashier'); self.assertEqual(first['id'],second['id']); self.assertEqual(first['total'],20000)
        self.assertEqual(self.ok('products')[0]['stock'],22); self.assertEqual(self.ok('members')[0]['points'],2)
        report=self.ok('report'); self.assertEqual(report['revenue'],20000); self.assertEqual(report['hpp'],12000); self.assertEqual(report['gross_profit'],8000); self.assertEqual(report['cash'],20000)
        d['tender']=30000; self.assertEqual(self.req('sales',d,self.cookies['cashier'])[0],409)
    def test_rejected_sale_rolls_back_everything(self):
        d=self.sale(25,member_id=1); self.assertEqual(self.req('sales',d,self.cookies['cashier'])[0],400)
        d=self.sale(1); d['tender']=1; self.assertEqual(self.req('sales',d,self.cookies['cashier'])[0],400)
        self.assertEqual(self.ok('products')[0]['stock'],24); self.assertEqual(self.ok('sales'),[]); self.assertEqual(self.ok('loyalty?member=1'),[]); self.assertEqual(self.ok('report')['cash'],0)
    def test_two_cashiers_cannot_oversell(self):
        self.ok('sales',self.sale(23),'cashier')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(self.req,'sales',self.sale(),self.cookies[who]) for who in ('cashier','manager')]
        self.assertEqual(sorted(f.result()[0] for f in futures),[200,400]); self.assertEqual(self.ok('products')[0]['stock'],0)
    def test_inventory_conversion_and_partial_receipt(self):
        self.assertEqual(self.ok('products')[0]['stock'],24)
        self.assertEqual(self.req('purchases/receive',{'id':1,'qty':1},self.cookies['warehouse'])[0],400)
        self.ok('purchases',{'product_id':1,'supplier_id':1,'qty':2,'cost':8000,'due':b.day()}); self.ok('purchases/approve',{'id':2}); self.ok('purchases/receive',{'id':2,'qty':1},'warehouse')
        p=self.ok('products')[0]; self.assertEqual(p['stock'],36); self.assertEqual(p['cost'],6667)
        movements=self.ok('inventory'); self.assertEqual(sum(m['qty'] for m in movements),36)
    def test_stock_count_approval_and_stale_rejection(self):
        self.ok('counts',{'product_id':1,'physical':20,'reason':'Hitung ulang'},'warehouse'); self.assertEqual(self.ok('products')[0]['stock'],24)
        self.assertEqual(self.req('counts/approve',{'id':1},self.cookies['warehouse'])[0],403)
        self.ok('counts/approve',{'id':1}); self.assertEqual(self.ok('products')[0]['stock'],20)
        self.ok('counts',{'product_id':1,'physical':19,'reason':'Hitung'},'warehouse'); self.ok('sales',self.sale(),'cashier')
        self.assertEqual(self.req('counts/approve',{'id':2},self.cookies['owner'])[0],409)
        self.ok('counts',{'product_id':1,'physical':18,'reason':'Owner hitung'})
        self.assertEqual(self.req('counts/approve',{'id':3},self.cookies['owner'])[0],400)
    def promo(self,**overrides):
        p=dict(code='HEMAT',title='Promo uji',strategy='Retensi',percent=10,minimum=10000,cap=5000,starts=b.day(),ends=b.day(),weekdays='0,1,2,3,4,5,6',member_only=True,quota=1); p.update(overrides); self.ok('promos',p,'manager'); return p
    def test_promo_approval_member_quota_and_margin(self):
        self.promo(); d=self.sale(member_id=1,promo='HEMAT')
        self.assertEqual(self.req('quote',d,self.cookies['cashier'])[0],400); self.ok('promos/approve',{'id':1})
        self.assertEqual(self.req('quote',self.sale(promo='HEMAT'),self.cookies['cashier'])[0],400)
        q=self.ok('quote',d,'cashier'); self.assertEqual(q['total'],9000); self.ok('sales',d,'cashier')
        self.assertEqual(self.req('quote',self.sale(member_id=1,promo='HEMAT'),self.cookies['cashier'])[0],400)
        self.promo(code='LOSS',percent=50); self.ok('promos/approve',{'id':2}); self.assertEqual(self.req('quote',self.sale(member_id=1,promo='LOSS'),self.cookies['cashier'])[0],400)
    def test_promo_schedule(self):
        weekday=str((b.datetime.now(b.TZ).weekday()+1)%7); self.promo(weekdays=weekday); self.ok('promos/approve',{'id':1}); self.assertEqual(self.req('quote',self.sale(member_id=1,promo='HEMAT'),self.cookies['cashier'])[0],400)
        self.promo(code='EXPIRED',starts='2000-01-01',ends='2000-01-02'); self.ok('promos/approve',{'id':2}); self.assertEqual(self.req('quote',self.sale(member_id=1,promo='EXPIRED'),self.cookies['cashier'])[0],400)
    def test_loyalty_redemption_and_refund(self):
        self.ok('sales',self.sale(10,member_id=1),'cashier'); s=self.ok('sales',self.sale(member_id=1,redeem=5),'cashier'); self.assertEqual(s['total'],9500); self.assertEqual(self.ok('members')[0]['points'],5)
        self.assertEqual(self.req('refund',{'id':s['id'],'reason':'retur'},self.cookies['cashier'])[0],403)
        self.ok('refund',{'id':s['id'],'reason':'Barang utuh dikembalikan'}); self.assertEqual(self.ok('members')[0]['points'],10); self.assertEqual(self.ok('products')[0]['stock'],14)
        self.assertEqual(self.req('refund',{'id':s['id'],'reason':'ulang'},self.cookies['owner'])[0],400)
    def test_shift_and_receipt_ownership(self):
        s=self.ok('sales',self.sale(),'cashier'); receipt=self.ok('receipt?id='+s['id'],who='cashier'); self.assertNotIn('cost',receipt); self.assertNotIn('cost',receipt['items'][0])
        result=self.ok('shifts/close',{'counted':109000},'cashier'); self.assertEqual(result['expected'],110000); self.assertEqual(result['difference'],-1000)
        self.assertEqual(self.req('sales',self.sale(),self.cookies['cashier'])[0],400)
        other=self.ok('sales',self.sale(),'manager'); self.assertEqual(self.req('receipt?id='+other['id'],cookie=self.cookies['cashier'])[0],403)
        self.assertEqual(len(self.ok('sales',who='cashier')),1)
    def test_payables_and_expenses_do_not_double_count_hpp(self):
        self.ok('cash',{'kind':'capital','amount':500000,'reason':'Modal awal'}); self.ok('purchases/pay',{'id':1,'amount':144000}); self.ok('cash',{'kind':'expense','amount':10000,'reason':'Listrik'})
        r=self.ok('report'); self.assertEqual(r['hpp'],0); self.assertEqual(r['expenses'],10000); self.assertEqual(r['cash'],346000); self.assertEqual(r['payables'],[]); self.assertEqual(r['operating_profit'],-10000)
    def test_sensitive_files_and_method_guard(self):
        c=http.client.HTTPConnection('127.0.0.1',self.port)
        for path in ('/backend.py','/data/nilla.sqlite3','/.git/config','/../README.md'):
            c.request('GET',path); r=c.getresponse(); self.assertEqual(r.status,404); r.read()
        c.close(); self.assertEqual(self.req('purchases/receive',cookie=self.cookies['owner'])[0],405)
        self.assertEqual(self.req('setup',{'name':'other','password':self.password})[0],409)
    def test_login_throttling_csrf_and_logout(self):
        for _ in range(5): self.assertEqual(self.req('login',{'name':'owner','password':'incorrect-long-password'})[0],401)
        self.assertEqual(self.req('login',{'name':'owner','password':self.password})[0],429)
        c=http.client.HTTPConnection('127.0.0.1',self.port); c.request('POST','/api/cash','{}',{'Cookie':self.cookies['owner'],'Content-Type':'application/json','X-Nilla-Request':'1','Origin':'https://evil.example'}); r=c.getresponse(); self.assertEqual(r.status,403); r.read(); c.close()
        self.ok('logout',{},'cashier'); self.assertEqual(self.req('products',cookie=self.cookies['cashier'])[0],401)
    def test_backup_restore_integrity(self):
        self.ok('sales',self.sale(member_id=1),'cashier'); target=Path(self.temp.name)/('backup-'+secrets.token_hex(4)+'.sqlite3')
        subprocess.run([sys.executable,str(b.ROOT/'backup.py'),str(b.DB),str(target)],check=True,capture_output=True)
        db=sqlite3.connect(target)
        try:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok'); self.assertEqual(db.execute('SELECT COUNT(*) FROM sales').fetchone()[0],1); self.assertEqual(db.execute('SELECT stock FROM products').fetchone()[0],23)
        finally:
            db.close()
        restore=Path(self.temp.name)/('restore-'+secrets.token_hex(4)+'.sqlite3'); subprocess.run([sys.executable,str(b.ROOT/'backup.py'),str(target),str(restore)],check=True,capture_output=True)
        original=b.DB
        try:
            b.DB=restore
            self.cookies['owner']=self.req('login',{'name':'owner','password':self.password})[2]
            self.assertEqual(self.ok('products')[0]['stock'],23); self.assertEqual(self.ok('members')[0]['points'],1); self.assertEqual(self.ok('report')['revenue'],10000)
        finally: b.DB=original

if __name__=='__main__': unittest.main(verbosity=2)
