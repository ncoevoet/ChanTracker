import BaseHTTPServer
import os
import time
import base64
import re
import supybot.utils as utils
import sqlite3
import collections
import urllib

host = 'http://domain.tld'
port = 6666
username = 'login'
password = 'password'
filename = '/home/user/bot/data/networkname/ChanTracker.db'
channels = ['#channelA','#channelb'] # empty to allows view of all channels recorded, otherwise restrict the views to channels

# usage python server.py

base64string = base64.encodestring('%s:%s' % (username,password))[:-1]

def timeElapsed(elapsed, short=False, leadingZeroes=False, years=True,
				weeks=True, days=True, hours=True, minutes=True, seconds=True):
	"""Given <elapsed> seconds, returns a string with an English description of
	how much time as passed.  leadingZeroes determines whether 0 days, 0 hours,
	etc. will be printed; the others determine what larger time periods should
	be used.
	"""
	ret = []
	def Format(s, i):
		if i or leadingZeroes or ret:
			if short:
				ret.append('%s%s' % (i, s[0]))
			else:
				ret.append(format('%n', (i, s)))
	elapsed = int(elapsed)
	assert years or weeks or days or \
		   hours or minutes or seconds, 'One flag must be True'
	if years:
		(yrs, elapsed) = (elapsed // 31536000, elapsed % 31536000)
		Format('year', yrs)
	if weeks:
		(wks, elapsed) = (elapsed // 604800, elapsed % 604800)
		Format('week', wks)
	if days:
		(ds, elapsed) = (elapsed // 86400, elapsed % 86400)
		Format('day', ds)
	if hours:
		(hrs, elapsed) = (elapsed // 3600, elapsed % 3600)
		Format('hour', hrs)
	if minutes or seconds:
		(mins, secs) = (elapsed // 60, elapsed % 60)
		if leadingZeroes or mins:
			Format('minute', mins)
		if seconds:
			leadingZeroes = True
			Format('second', secs)
	if not ret:
		raise ValueError, 'Time difference not great enough to be noted.'
	if short:
		return ' '.join(ret)
	else:
		return format('%L', ret)

class MyHandler( BaseHTTPServer.BaseHTTPRequestHandler ):
	server_version= "Ircd-Seven/1.1"
	def do_GET( self ):
		self.page( self.path )

	def page (self,query):
		h = '%s:%s/' % (host,port)
		if not query:
			return
		if query.startswith('/?username='):
			query = query.replace('/?','')
			a = query.split('&')
			u = p = None
			for item in a:
				aa = item.split('=')
				if aa[0] == 'username':
					u = aa[1]
				if aa[0] == 'password':
					p = aa[1]
			if u and p:
				raw = base64.encodestring('%s:%s' % (u,p))[:-1]
				if not raw == base64string:
					query = ''
				else:
					query = '/?hash=%s' % base64string
		if not query.startswith('/?hash='):
			body = '<html>\n<head>\n<title>ChanTracker</title>\n'
			body += '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
			body += "</head>\n<body>\n"
			body += '<form action="%s">\n' % h
			body += '<p>Username:<input name="username" /></p>\n' 
			body += '<p>Password:<input name="password" type="password"/></p>\n'
			body += '<input type="submit" value="Login" />\n'
			body += "</form>\n"
			body += "</body>\n<html>\n"
			self.send_response(200)
			self.send_header("Content-type","text/html")
			self.send_header("Content-length",str(len(body)))
			self.end_headers()
			self.wfile.write(body)
			return
		if query.startswith('/?hash='):
			a = query.split('&')[0]
			a = a.replace('/?hash=','')
			query = query.replace('%3D','=')
			query = query.replace('/?hash=%s' % base64string,'/')
			q = '?hash=%s' % base64string
			query = urllib.unquote( query )
			print query
		body = '<html style="text-align:center;font-size:1.2em;">\n<head>\n<title>BanTracker - %s</title>\n' % query
		body += '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
		body += '<link rel="stylesheet" href="http://getbootstrap.com/dist/css/bootstrap.min.css"></link>\n'
		body += '<script src="http://www.kryogenix.org/code/browser/sorttable/sorttable.js"></script>\n'
		body += '</head>\n<body style="margin:0.5em;width:98%;margin-left:auto;margin-right:auto;text-align:left;" class="container">\n'
		body += '<div class="row"><div class="col-xs-6">\n'
		body += '<form action="%s" class="form">\n' % q
		body += '<div class="input-group">'
		body += '<input type="hidden" name="hash" value="%s">' % base64string
		body += '<input name="search" class="form-control" />\n'
		body += '<span class="input-group-btn"><button type="submit" class="btn btn-default">Search</button></span>\n'
		body += '</div></form></div>\n'
		body += '<div class="clearfix"></div>\n'
		db = self._getbandb()
		c = db.cursor()
		if query:
			ar = []
			if query.startswith('/&id='):
				search = query.split('/&id=')[1]
				c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=? ORDER BY id DESC""",(search,))
				if c.rowcount:
					ban = c.fetchall()[0]
					(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
					if not len(channels) or channel in channels:
						body += '<h3>#%s</h3>\n' % id
						body += '<p>#%s by %s in %s : +%s : %s</p>\n' % (id,oper,channel,kind,mask)
						body += '<p>Begin at %s</p>\n' % time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(begin_at)))
						was = float(begin_at) == float(end_at)
						if was:
							was = 'forever'
						else:
							was = timeElapsed(float(end_at) - float(begin_at))
						body += '<p>Original duration : %s</p>\n' % was
						if not removed_at:
							if was != 'forever':
								body += '<p>%s</p>\n' % 'It will expire in %s' % timeElapsed(float(end_at) - time.time())
						else:
							body += '<p>%s</p>\n' % 'Removed after %s on %s by %s' % (timeElapsed(float(removed_at)-float(begin_at)),time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(removed_at))),removed_by)
						c.execute("""SELECT full, log FROM nicks WHERE ban_id=?""",(id,))
						if c.rowcount:
							users = c.fetchall()
							body += '<h3>Logs</h3>\n'
							for u in users:
								(full,log) = u
								body += '<p>for %s</p>\n' % full
								if log != '':
									body +='<ul>\n'
									for line in log.split('\n'):
										 if line != '':
											 body += '<li>%s</li>\n' % line
									body += '</ul>\n'
						c.execute("""SELECT oper, at, comment FROM comments WHERE ban_id=?""",(id,))
						if c.rowcount:
							body += '<h3>Comments</h3>\n'
							body += '<ul>\n'
							comments = c.fetchall()
							for com in comments:
								(oper,at,comment) = com
								s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(at)))
								body += '<li>%s by %s : %s</li>\n' % (s,oper,comment)
							body += '</ul>\n'
			if query.startswith('/&channel='):
				search = '#'+query.split('/&channel=')[1]
				c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE channel=? ORDER BY id DESC""",(search,))
				if c.rowcount:
					bans = c.fetchall()
					for ban in bans:
						(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
						ar.append([int(id),channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by])
			if query.startswith('/&removed_by='):
				search = query.split('/&removed_by=')[1]
				c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE removed_by=? ORDER BY id DESC""",(search,))
				if c.rowcount:
					bans = c.fetchall()
					for ban in bans:
						(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
						ar.append([int(id),channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by])               
			if query.startswith('/&oper='):
				search = query.split('/&oper=')[1]
				c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE oper=? ORDER BY id DESC""",(search,))
				if c.rowcount:
					bans = c.fetchall()
					for ban in bans:
						(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
						ar.append([int(id),channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by])
			if query.startswith('/&mask='):
				search = query.split('/&mask=')[1]
				glob = '*%s*' % search
				like = '%'+search+'%' 
				c.execute("""SELECT ban_id, full FROM nicks WHERE full GLOB ? OR full LIKE ? OR log GLOB ? OR log LIKE ? ORDER BY ban_id DESC""",(glob,like,glob,like))
				L = [] 
				a = {} 
				if c.rowcount:
					bans = c.fetchall()
					d = {}
					for ban in bans:
						(id,full) = ban
						if not id in d:
							d[id] = id
					for id in d:
						c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=? ORDER BY id DESC""",(int(id),))
						if c.rowcount:
							bans = c.fetchall()
							for ban in bans:
								(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
								a[str(id)] = ban
				c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE mask GLOB ? OR mask LIKE ? ORDER BY id DESC""",(glob,like))
				if c.rowcount:
					bans = c.fetchall()
					for ban in bans:
						(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
						a[str(id)] = ban
				if len(a):
					ar = []
					for ban in a:
						(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = a[ban]
						ar.append([int(id),channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by])
					def sort_function (item):
						return item[0]
					ar.sort(key=sort_function)
					ar.sort(reverse=True)
			if query.startswith('/&search='):
				search = query.split('/&search=')[1]
				search = search.replace('+','*')
				print search
				if search:
					s = '*%s*' % search
					qu = '%'+search+'%'
					c.execute("""SELECT ban_id, full FROM nicks WHERE full GLOB ? OR full LIKE ? OR log GLOB ? OR log LIKE  ? ORDER BY ban_id DESC""",(s,qu,s,qu))
					L = []
					a = {}
					if c.rowcount:
						bans = c.fetchall()
						d = {}
						for ban in bans:
							(id,full) = ban
							if not id in d:
								d[id] = id
						for id in d:
							c = db.cursor()
							c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=? ORDER BY id DESC""",(int(id),))
							if c.rowcount:
								bans = c.fetchall()
								for ban in bans:
									(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
									a[id] = ban
					c = db.cursor()
					c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE mask GLOB ? OR mask LIKE ? OR channel GLOB ? OR channel LIKE ? OR oper GLOB ? OR oper LIKE ? ORDER BY id DESC""",(s,qu,s,qu,s,qu))
					if c.rowcount:
						bans = c.fetchall()
						for ban in bans:
							(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
							a[id] = ban
					c = db.cursor()
					c.execute("""SELECT ban_id, comment FROM comments WHERE comment GLOB ? OR comment LIKE ? ORDER BY ban_id DESC""",(s,qu))
					d = {}
					if c.rowcount:
						bans = c.fetchall()
						for ban in bans:
							(id,full) = ban
							d[id] = id
						for id in d:
							if not id in a:
								c = db.cursor()
								c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=? ORDER BY id DESC""",(int(id),))
								if c.rowcount:
									bans = c.fetchall()
									for ban in bans:
										(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
										a[id] = ban
					if len(a):
						ar = []
						for ban in a:
							(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = a[ban]
							ar.append([int(id),channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by])
						def sort_function (item):
							return item[0]
						ar.sort(key=sort_function)
						ar.sort(reverse=True)
				else:
					body += '<p>nothing found</p>\n'
			if len(ar):
				i = 0
				body += '<h3>results <small>%s</small></h3>' % search
				body += '<table class="table table-bordered sortable">\n'
				body += '<thead><tr><th>ID</th><th>Channel</th><th>Operator</th><th>Kind</th><th>Target</th><th>Begin date</th><th>End date</th><th>Removed date</th><th>Removed by</th><th>affected</th></tr></thead>\n'
				body += '<tbody>\n'
				while i < len(ar):
					(id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ar[i]
					if not len(channels) or channel in channels:
						body += '<tr>\n'
						body += '<td><a href="%s%s&id=%s">%s</a></td>\n' % (h,q,id,id)
						body += '<td><a href="%s%s&channel=%s">%s</a></td>\n' % (h,q,channel.split('#')[1],channel)
						body += '<td><a href="%s%s&%s">%s</a></td>\n' % (h,q,urllib.urlencode({'oper':oper}),oper)
						body += '<td>+%s</td>\n' % kind
						body += '<td><a href="%s%s&%s">%s</a></td>\n' % (h,q,urllib.urlencode({'mask':mask}),mask)
						s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(begin_at)))
						body += '<td>%s</td>\n' % s
						if end_at and end_at != begin_at:
							s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(end_at)))
							body += '<td>%s</td>\n' % s
						else:
							body += '<td></td>'
						if removed_at:
							s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(removed_at)))
							body += '<td>%s</td>' % s
						else:
							body += '<td></td>\n' 
						if removed_by:
							body += '<td><a href="%s%s&%s">%s</a></td>\n' % (h,q,urllib.urlencode({'removed_by':removed_by}),removed_by)
						else:
							body += '<td></td>\n'
						affected = ''
						try:
							c.execute("""SELECT full, log FROM nicks WHERE ban_id=?""",(id,))
							affected = len(c.fetchall())
						except:
							affected = ''
						body += '<td>%s</td>\n' % affected
						body += '</tr>\n'
					i = i+1
				body += '</tbody>\n'
				body += '</table>\n'
		c.close()
		body += "</body></html>"
		self.send_response(200)
		self.send_header("Content-type","text/html")
		self.send_header("Content-length",str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def _getbandb (self):
		if os.path.exists(filename):
			db = sqlite3.connect(filename,timeout=10)
			db.text_factory = str
			return db
		db = sqlite3.connect(filename)
		db.text_factory = str
		c = db.cursor()
		c.execute("""CREATE TABLE bans (
				id INTEGER PRIMARY KEY,
				channel VARCHAR(100) NOT NULL,
				oper VARCHAR(1000) NOT NULL,
				kind VARCHAR(1) NOT NULL,
				mask VARCHAR(1000) NOT NULL,
				begin_at TIMESTAMP NOT NULL,
				end_at TIMESTAMP NOT NULL,
				removed_at TIMESTAMP,
				removed_by VARCHAR(1000)
				)""")
		c.execute("""CREATE TABLE nicks (
				ban_id INTEGER,  
				ban VARCHAR(1000) NOT NULL,
				full VARCHAR(1000) NOT NULL,
				log TEXT NOT NULL  
				)""")
		c.execute("""CREATE TABLE comments (
				ban_id INTEGER,
				oper VARCHAR(1000) NOT NULL,    
				at TIMESTAMP NOT NULL,
				comment TEXT NOT NULL
				)""")
		db.commit()
		return db

def httpd(handler_class=MyHandler, server_address = ('', port), ):
	srvr = BaseHTTPServer.HTTPServer(server_address, handler_class)
	srvr.serve_forever()

if __name__ == "__main__":
	httpd( )

