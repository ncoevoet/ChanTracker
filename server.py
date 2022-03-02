import os, re, time, base64
import supybot.utils as utils
import http.server, sqlite3

host = 'http://domain.tld'
port = 80
standalone = True
webpath = '/bantracker'
username = 'username'
password = 'password'
filename = '/home/botaccount/data/networkname/ChanTracker.db'
channels = [] # empty to allow view of all channels recorded, otherwise restrict the views to channels

# usage python server.py
auth = '%s:%s' % (username,password)
base64string = base64.b64encode(auth.encode('utf-8')).decode('utf-8')

def weblink():
	weblink = host
	if standalone:
		weblink += ':%s' % port
	else:
		weblink += webpath
	weblink += '/?hash=%s' % base64string
	return weblink

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
		raise ValueError('Time difference not great enough to be noted.')
	if short:
		return ' '.join(ret)
	else:
		return format('%L', ret)

def htmlEscape(text):
	return text.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')


class MyHandler(http.server.BaseHTTPRequestHandler):
	if not standalone:
		def log_request(self, *args):
			pass    # disable logging

	def do_GET(self):
		self.page(self.path)

	def page(self, query):
		def write(subtitle, body):
			page = [
				'<!DOCTYPE html>', '<html>', '<head>',
				'<title>BanTracker%s</title>' % (' &raquo; %s' % subtitle if subtitle else ''),
				'<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />',
				'<link rel="stylesheet" href="//maxcdn.bootstrapcdn.com/bootstrap/3.3.4/css/bootstrap.min.css" />',
				'</head>', '<body style="margin:0.5em; width:98%;" class="container">'
			] + body + ['</body>', '</html>']
			self.send_response(200)
			self.send_header("Content-Type", "text/html")
			full = '\n'.join(page)
			print('HTML lines %s' % len(full))
			self.send_header("Content-Length", len(full))
			self.end_headers()
			self.wfile.write(full.encode('utf-8'))

		if standalone:
			h = '%s:%s/' % (host,port)
		else:
			h = '%s/' % webpath
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
				auth = '%s:%s' % (u,p)
				raw = base64.b64encode(auth.encode('utf-8')).decode('utf-8')
				if raw != base64string:
					query = ''
				else:
					query = '/?hash=%s' % base64string
		if not query.startswith('/?hash='):
			subtitle = ''
			body = [
				'<form action="%s">' % h,
				'<p>Username: <input name="username" /></p>',
				'<p>Password: <input name="password" type="password" /></p>',
				'<button type="submit" class="btn btn-default">Login</button>',
				'</form>'
			]
			write(subtitle, body)
			return
		query = query.replace('%3D','=')
		query = query.replace('/?hash=%s' % base64string,'')
		query = query.lstrip('&')
		q = '?hash=%s' % base64string
		query = utils.web.urlunquote(query)
		subtitle = ''
		body = [
			'<div class="row"><div class="col-xs-6" style="width:100%; max-width:600px;">',
			'<form action="%s" class="form">' % q,
			'<div class="input-group">',
			'<input type="hidden" name="hash" value="%s">' % base64string,
			'<input name="search" class="form-control" />',
			'<span class="input-group-btn"><button type="submit" class="btn btn-default">Search</button></span>',
			'</div></form></div></div>',
			'<div class="clearfix"></div>'
		]
		if not query:
			write(subtitle, body)
			return
		print(query)
		subtitle = query
		db = self._getbandb()
		c = db.cursor()
		ar = []
		if query.startswith('id='):
			search = query.split('=')[1]
			si = int(search)
			c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(si,))
			r = c.fetchall()
			if len(r):
				ban = r[0]
				(bid,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
				if not channels or channel in channels:
					body.extend([
						'<h3>#%d</h3>' % bid,
						'<p>#%d by <a href="%s%s&amp;%s">%s</a>' % (bid,h,q,utils.web.urlencode({'oper':oper}),oper),
						'in <a href="%s%s&amp;channel=%s">%s</a>:' % (h,q,channel.split('#')[1],channel),
						'+%s <a href="%s%s&amp;%s">%s</a></p>' % (kind,h,q,utils.web.urlencode({'mask':mask}),mask),
						'<p>Begin at %s</p>' % time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(begin_at)))
					])
					was = float(begin_at) == float(end_at)
					if was:
						was = 'forever'
					else:
						was = timeElapsed(float(end_at) - float(begin_at))
					body.append('<p>Original duration: %s</p>' % was)
					if not removed_at:
						if was != 'forever':
							body.append('<p>It will expire in %s</p>' % timeElapsed(float(end_at) - time.time()))
					else:
						body.extend(['<p>Removed after %s' % timeElapsed(float(removed_at)-float(begin_at)),
								'on %s' % time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(removed_at))),
								'by <a href="%s%s&amp;%s">%s</a></p>' % (h,q,utils.web.urlencode({'removed_by':removed_by}),removed_by)])
					c.execute("""SELECT full,log FROM nicks WHERE ban_id=?""",(bid,))
					r = c.fetchall()
					if len(r):
						body.append('<h3>Logs</h3>')
						for (full,log) in r:
							body.append('<p>for %s</p>' % full)
							if log != '':
								body.append('<ul>')
								for line in log.split('\n'):
									if line != '':
										body.append('<li>%s</li>' % htmlEscape(line))
								body.append('</ul>')
					c.execute("""SELECT oper,at,comment FROM comments WHERE ban_id=?""",(bid,))
					r = c.fetchall()
					if len(r):
						body.extend(['<h3>Comments</h3>', '<ul>'])
						for (oper,at,com) in r:
							s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(at)))
							body.append('<li>%s by %s: %s</li>' % (s,oper,htmlEscape(com)))
						body.append('</ul>')
			c.close()
			write(subtitle, body)
			return
		elif query.startswith('channel='):
			search = '#'+query.split('=')[1]
			c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE channel=? ORDER BY id DESC""",(search,))
			r = c.fetchall()
			if len(r):
				ar.extend(r)
		elif query.startswith('removed_by='):
			search = query.split('=')[1]
			c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE removed_by=? ORDER BY id DESC""",(search,))
			r = c.fetchall()
			if len(r):
				ar.extend(r)
		elif query.startswith('oper='):
			search = query.split('=')[1]
			c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE oper=? ORDER BY id DESC""",(search,))
			r = c.fetchall()
			if len(r):
				ar.extend(r)
		elif query.startswith('mask='):
			search = query.split('=')[1]
			sg = '*%s*' % search
			sl = '%%%s%%' % search
			c.execute("""SELECT ban_id,full FROM nicks WHERE full GLOB ? OR full LIKE ? OR log GLOB ? OR log LIKE ? ORDER BY ban_id DESC""",(sg,sl,sg,sl))
			r = c.fetchall()
			L = []
			a = {}
			if len(r):
				d = []
				for (bid,full) in r:
					if bid not in d:
						d.append(bid)
				for bid in d:
					c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(bid,))
					r = c.fetchall()
					if len(r):
						for ban in r:
							a[ban[0]] = ban
			c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE mask GLOB ? OR mask LIKE ? ORDER BY id DESC""",(sg,sl))
			r = c.fetchall()
			if len(r):
				for ban in r:
					a[ban[0]] = ban
			if len(a):
				ar = []
				for ban in list(a.keys()):
					ar.append(a[ban])
				ar.sort(key=lambda x: x[0], reverse=True)
		elif query.startswith('search='):
			search = query.split('=')[1]
			search = search.replace('+','*')
			print(search)
			if search:
				if not re.match(r'^[0-9]+$', search):
					sg = '*%s*' % search
					sl = '%%%s%%' % search
					si = None
					c.execute("""SELECT ban_id,full FROM nicks WHERE full GLOB ? OR full LIKE ? OR log GLOB ? OR log LIKE ? ORDER BY ban_id DESC""",(sg,sl,sg,sl))
					r = c.fetchall()
				else:
					si = int(search)
					r = []
				L = []
				a = {}
				if len(r):
					d = []
					for (bid,full) in r:
						if bid not in d:
							d.append(bid)
					for bid in d:
						c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(bid,))
						r = c.fetchall()
						if len(r):
							for ban in r:
								a[ban[0]] = ban
				if not si:
					c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE mask GLOB ? OR mask LIKE ? OR channel GLOB ? OR channel LIKE ? OR oper GLOB ? OR oper LIKE ? ORDER BY id DESC""",(sg,sl,sg,sl,sg,sl))
				else:
					c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(si,))
				r = c.fetchall()
				if len(r):
					for ban in r:
						a[ban[0]] = ban
				if not si:
					c.execute("""SELECT ban_id, comment FROM comments WHERE comment GLOB ? OR comment LIKE ? ORDER BY ban_id DESC""",(sg,sl))
					r = c.fetchall()
				else:
					r = []
				if len(r):
					d = []
					for (bid,full) in r:
						d.append(bid)
					for bid in d:
						if bid not in a:
							c.execute("""SELECT id,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by FROM bans WHERE id=?""",(bid,))
							r = c.fetchall()
							if len(r):
								for ban in r:
									a[ban[0]] = ban
				if len(a):
					ar = []
					for ban in list(a.keys()):
						ar.append(a[ban])
					ar.sort(key=lambda x: x[0], reverse=True)
		if len(ar):
			print('Found %s results' % len(ar))
			body.extend([
				'<h3>Results <small>%s</small></h3>' % search,
				'<div class="row"><div class="col-xs-12"><table class="table table-bordered">',
				'<thead><tr><th>ID</th><th>Channel</th><th>Operator</th><th>Type</th><th>Mask</th><th>Begin date</th><th>End date</th><th>Removed</th><th>Removed by</th></tr></thead>',
				'<tbody>'
			])
			for ban in ar:
				(bid,channel,oper,kind,mask,begin_at,end_at,removed_at,removed_by) = ban
				if not channels or channel in channels:
					s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(begin_at)))
					body.extend([
						'<tr>',
						'<td><a href="%s%s&amp;id=%d">%d</a></td>' % (h,q,bid,bid),
						'<td><a href="%s%s&amp;channel=%s">%s</a></td>' % (h,q,channel.split('#')[1],channel),
						'<td><a href="%s%s&amp;%s">%s</a></td>' % (h,q,utils.web.urlencode({'oper':oper}),oper),
						'<td>+%s</td>' % kind,
						'<td><a href="%s%s&amp;%s">%s</a></td>' % (h,q,utils.web.urlencode({'mask':mask}),mask),
						'<td>%s</td>' % s
					])
					if end_at and end_at != begin_at:
						s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(end_at)))
						body.append('<td>%s</td>' % s)
					else:
						body.append('<td></td>')
					if removed_at:
						s = time.strftime('%Y-%m-%d %H:%M:%S GMT',time.gmtime(float(removed_at)))
						body.append('<td>%s</td>' % s)
					else:
						body.append('<td></td>')
					if removed_by:
						body.append('<td><a href="%s%s&amp;%s">%s</a></td>' % (h,q,utils.web.urlencode({'removed_by':removed_by}),removed_by))
					else:
						body.append('<td></td>')
#					affected = ''
#					try:
#						c.execute("""SELECT full, log FROM nicks WHERE ban_id=?""",(bid,))
#						affected = len(c.fetchall())
#					except:
#						affected = ''
#					body.append('<td>%s</td>' % affected)
					body.append('</tr>')
			body.extend(['</tbody>', '</table></div>'])
		else:
			body.append('<p>Nothing found</p>')
		c.close()
		write(subtitle, body)

	def _getbandb(self):
		if os.path.exists(filename):
			db = sqlite3.connect(filename,timeout=10)
			return db
		db = sqlite3.connect(filename)
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


def httpd(handler_class=MyHandler, server_address=('', port)):
	srvr = http.server.HTTPServer(server_address, handler_class)
	srvr.serve_forever()

if __name__ == "__main__":
	httpd()
