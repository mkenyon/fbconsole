#!/usr/bin/env python
#
# Copyright 2010 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import BaseHTTPServer
import cookielib
import httplib
import json
import mimetools
import mimetypes
import os
import os.path
import stat
import time
import types
import urllib2
import webbrowser

from urlparse import urlparse, parse_qs
from urllib import urlencode
from pprint import pprint

APP_ID = '179745182062082'
SERVER_PORT = 8080
ACCESS_TOKEN = None
ACCESS_TOKEN_FILE = '.fb_access_token'
AUTH_SCOPE = []

__all__ = [
    'help',
    'authenticate',
    'logout',
    'get',
    'post',
    'delete',
    'shell',
    'fql',
    'APP_ID',
    'SERVER_PORT',
    'ACCESS_TOKEN',
    'AUTH_SCOPE',
    'ACCESS_TOKEN_FILE']

def _get_url(path, args=None, graph=True):
    args = args or {}
    if ACCESS_TOKEN:
        args['access_token'] = ACCESS_TOKEN
    if graph:
        subdomain = 'graph'
        if '/videos' in path:
            subdomain = 'graph-video'
    else:
        subdomain = 'graph' if graph else 'api'
    if 'access_token' in args or 'client_secret' in args:
        endpoint = "https://%s.facebook.com" % subdomain
    else:
        endpoint = "http://%s.facebook.com" % subdomain
    return endpoint+str(path)+'?'+urlencode(args)

class _MultipartPostHandler(urllib2.BaseHandler):
    handler_order = urllib2.HTTPHandler.handler_order - 10 # needs to run first

    def http_request(self, request):
        data = request.get_data()
        if data is not None and not isinstance(data, types.StringTypes):
            files = []
            params = []
            try:
                for key, value in data.items():
                    if isinstance(value, types.FileType):
                        files.append((key, value))
                    else:
                        params.append((key, value))
            except TypeError:
                raise TypeError("not a valid non-string sequence or mapping object")

            if len(files) == 0:
                data = urlencode(params)
            else:
                boundary, data = self.multipart_encode(params, files)
                contenttype = 'multipart/form-data; boundary=%s' % boundary
                request.add_unredirected_header('Content-Type', contenttype)

            request.add_data(data)
        return request

    https_request = http_request

    def multipart_encode(self, params, files, boundary=None, buffer=None):
        boundary = boundary or mimetools.choose_boundary()
        buffer = buffer or ''
        for key, value in params:
            buffer += '--%s\r\n' % boundary
            buffer += 'Content-Disposition: form-data; name="%s"' % key
            buffer += '\r\n\r\n' + value + '\r\n'
        for key, fd in files:
            file_size = os.fstat(fd.fileno())[stat.ST_SIZE]
            filename = fd.name.split('/')[-1]
            contenttype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            buffer += '--%s\r\n' % boundary
            buffer += 'Content-Disposition: form-data; '
            buffer += 'name="%s"; filename="%s"\r\n' % (key, filename)
            buffer += 'Content-Type: %s\r\n' % contenttype
            fd.seek(0)
            buffer += '\r\n' + fd.read() + '\r\n'
        buffer += '--%s--\r\n\r\n' % boundary
        return boundary, buffer


class _RequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def do_GET(self):
        global ACCESS_TOKEN
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        params = parse_qs(urlparse(self.path).query)
        ACCESS_TOKEN = params.get('access_token', [None])[0]
        if ACCESS_TOKEN:
            data = {'scope': AUTH_SCOPE,
                    'access_token': ACCESS_TOKEN}
            expiration = params.get('expires_in', [None])[0]
            if expiration:
                if expiration == '0':
                    # this is what's returned when offline_access is requested
                    data['expires_at'] = 'never'
                else:
                    data['expires_at'] = int(time.time()+int(expiration))
            open(ACCESS_TOKEN_FILE,'w').write(json.dumps(data))
            self.wfile.write("You have successfully logged in to facebook with fbconsole. "
                             "You can close this window now.")
        else:
            self.wfile.write('<html><head>'
                             '<script>location = "?"+location.hash.slice(1);</script>'
                             '</head></html>')

def help():
    """Print out some helpful information"""
    print '''
The following commands are available:

help() - display this help message
authenticate() - authenticate with facebook.
logout() - Remove the cached access token, forcing authenticate() to get a new
           access token
get(path, params) - call the graph api with the given path and query parameters
post(path, data) - post data to the graph api with the given path
delete(path, params) - send a delete request
fql(query) - make an fql request
'''

def authenticate():
    """Authenticate with facebook so you can make api calls that require auth.

    Alternatively you can just set the ACCESS_TOKEN global variable in this
    module to an access token you get from facebook.

    If you want to request certain permissions, set the AUTH_SCOPE global
    variable to the list of permissions you want.
    """
    global ACCESS_TOKEN
    needs_auth = True
    if os.path.exists(ACCESS_TOKEN_FILE):
        data = json.loads(open(ACCESS_TOKEN_FILE).read())
        expires_at = data.get('expires_at')
        still_valid = expires_at and (expires_at == 'never' or expires_at > time.time())
        if still_valid and set(data['scope']).issuperset(AUTH_SCOPE):
            ACCESS_TOKEN = data['access_token']
            needs_auth = False

    if needs_auth:
        print "Logging you in to facebook..."
        webbrowser.open('https://www.facebook.com/dialog/oauth?' +
                        urlencode({'client_id':APP_ID,
                                   'redirect_uri':'http://127.0.0.1:%s/' % SERVER_PORT,
                                   'response_type':'token',
                                   'scope':','.join(AUTH_SCOPE)}))

        httpd = BaseHTTPServer.HTTPServer(('127.0.0.1', SERVER_PORT), _RequestHandler)
        while ACCESS_TOKEN is None:
            httpd.handle_request()

def logout():
    """Logout of facebook.  This just removes the cached access token."""
    if os.path.exists(ACCESS_TOKEN_FILE):
        os.remove(ACCESS_TOKEN_FILE)

def get(path, params=None):
    """Send a GET request to the graph api.

    For example:

      >>> get('/me')
      >>> get('/me', {'fields':'id,name'})

    """
    return json.load(urllib2.urlopen(_get_url(path, args=params)))

def post(path, params=None):
    """Send a POST request to the graph api.

    You can also upload files using this function.  For example:

      >>> post('/me/photos',
      ...            {'name': 'My Photo',
      ...             'source': open("myphoto.jpg")})

    """
    opener = urllib2.build_opener(
        urllib2.HTTPCookieProcessor(cookielib.CookieJar()),
        _MultipartPostHandler)
    return json.load(opener.open(_get_url(path), params))

def delete(path, params=None):
    """Send a DELETE request to the graph api.

    For example:

      >>> msg_id = post('/me/feed', {'message':'hello world'})['id']
      >>> delete('/'+msg_id)

    """
    if not params:
        params = {}
    params['method'] = 'delete'
    return post(path, params)

def fql(query):
    """Make an fql request.

    For example:

      >>> fql('SELECT name FROM user WHERE uid = me()')

    """
    url = _get_url('/method/fql.query',
                   args={'query': query, 'format': 'json'},
                   graph=False)
    return json.load(urllib2.urlopen(url))

INTRO_MESSAGE = '''\
  __ _                                _
 / _| |                              | |
| |_| |__   ___  ___  _ __  ___  ___ | | ___
|  _| '_ \ / __|/ _ \| '_ \/ __|/ _ \| |/ _ \\
| | | |_) | (__| (_) | | | \__ \ (_) | |  __/
|_| |_.__/ \___|\___/|_| |_|___/\___/|_|\___|

Type help() for a list of commands.
quick start:

  >>> authenticate()
  >>> print "Hello", get('/me')['name']

'''

def shell():
    try:
        from IPython.Shell import IPShellEmbed
        IPShellEmbed()(INTRO_MESSAGE)
    except ImportError:
        import code
        code.InteractiveConsole(globals()).interact(INTRO_MESSAGE)

if __name__ == '__main__':
    shell()
