import os
import sys
import webapp2
import json
import jinja2
import datetime
import time
import markupsafe
import logging
from markupsafe import Markup, escape
from google.appengine.ext import db
from google.appengine.api import memcache

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)
sys.path.append(os.path.join(os.path.dirname(__file__), 'lib'))

import markdown2
import auth_helpers
import valid_helpers

### CACHE HELPERS ###
def get_top_posts(update = False):
    key = 'top'
    posts = memcache.get(key)
    if posts is None or update:
        posts = db.GqlQuery("SELECT * FROM Post WHERE is_draft = FALSE AND is_quote = FALSE ORDER BY created DESC")
        posts = list(posts)
        memcache.set(key, posts)
    return posts

def get_top_quotes(update = False):
    key = 'quote'
    posts = memcache.get(key)
    if posts is None or update:
        posts = db.GqlQuery("SELECT * FROM Post WHERE is_draft = FALSE AND is_quote = TRUE ORDER BY created DESC")
        posts = list(posts)
        memcache.set(key, posts)
    return posts

def get_requested_post(post_id):
    my_post = memcache.get(post_id)
    if my_post is None:
        my_post = Post.get_by_id(int(post_id))
        memcache.set(post_id, my_post)
        memcache.set("(post_time, %s)" % post_id, time.time())
    return my_post

### BASE HANDLER CLASS ###
class Handler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)

    def render_str(self, template, **params):
        t = jinja_env.get_template(template)
        return t.render(params)

    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def logged_in(self):
        cookie_val = self.request.cookies.get("logged_in")
        if cookie_val:
            return auth_helpers.check_secure_val(cookie_val) == "1"
        else:
            return False

    def logout(self):
        self.response.delete_cookie("logged_in")

    def login(self):
        self.response.set_cookie("logged_in",
                                 auth_helpers.make_secure_val("1"))

class LoginHandler(Handler):
    def get(self):
        self.render("login.html")

    def post(self):
        user_username = self.request.get('username')
        user_password = self.request.get('password')
        params = dict(username = user_username)
        if user_username == "class8e" and user_password == "bhs":
            self.redirect('/')
            self.login()
        else:
            params["error_username"] = "Invalid login"
            params["error_password"] = " "
            self.render("login.html", **params)

class LogoutHandler(Handler):
    def get(self):
        self.logout()
        self.redirect('/')

### BLOG STUFF ###
class Post(db.Model):
    subject = db.StringProperty(required = True)
    content = db.TextProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)
    last_modified = db.DateTimeProperty(auto_now_add = True)
    is_draft = db.BooleanProperty()
    is_quote = db.BooleanProperty(required = True)

class MainPage(Handler):
    def get(self):
        posts = get_top_posts() 
        self.render("home.html", posts=posts)

class BlogHandler(Handler):
    def get(self):
        posts = get_top_posts() 
        self.render("archives.html", posts=posts)

class QuotesHandler(Handler):
    def get(self):
        quotes = get_top_quotes()
        self.render("quotes.html", quotes = quotes)

class JsonPostHandler(Handler):
    def get(self):
        self.response.headers['Content-type'] = 'application/json'
        posts = db.GqlQuery("SELECT * FROM Post WHERE is_draft = FALSE ORDER BY created DESC")
        post_dict = []
        for my_post in posts:
            post_dict.append({"subject" : my_post.subject, "content" : my_post.content, 
                            "created" : my_post.created.strftime('%a %b %d %H:%M:%S %Y'),
                            "last_modified" : my_post.last_modified.strftime('%a %b %d %H:%M:%S %Y')})

        self.write(json.dumps(post_dict, indent=4))

class NewPostHandler(Handler):
    def get(self):
        if self.logged_in():
            self.render("newpost.html")
        else:
            self.abort(403)

    def post(self):
        if self.logged_in():
            self.render("newpost.html")
            subject = self.request.get("subject")
            content = Markup(markdown2.markdown(self.request.get("content")))
            is_quote = self.request.get("is_quote")
            is_draft = self.request.get("is_draft")
            
            if subject and content:
                p = Post(subject = subject, content = content,
                        is_draft = (is_draft == "on"),
                        is_quote = (is_quote == "on"))
                p.put()
                if is_draft == "on":
                    self.redirect('/drafts')
                elif is_quote == "on":
                    get_top_quotes(update = True)
                    self.redirect('/quotes')
                else:
                    get_top_posts(update = True)
                    self.redirect('/')
            else:
                error = "Both subject and content please!"
                self.render("newpost.html", subject = subject, content = content, error = error)
        else:
            self.abort(403)

class ShowPostHandler(Handler):
    def get(self, post_id):
        my_post = get_requested_post(post_id)
        self.render("showpost.html", my_post = my_post, 
                                     logged_in = self.logged_in())

class ShowPostJsonHandler(Handler):
    def get(self, post_id):
        self.response.headers['Content-type'] = 'application/json'
        my_post = Post.get_by_id(int(post_id))
        post_dict = {"subject" : my_post.subject, "content" : my_post.content, 
                    "created" : my_post.created.strftime('%a %b %d %H:%M:%S %Y'),
                    "last_modified" : my_post.last_modified.strftime('%a %b %d %H:%M:%S %Y')}
        self.write(json.dumps(post_dict, indent=4))

class EditPostHandler(Handler):
    def get(self, post_id):
        if self.logged_in():
            my_post = Post.get_by_id(int(post_id))
            self.render("editpost.html", subject = my_post.subject, content = my_post.content)
        else:
            self.abort(403)

    def post(self, post_id):
        if self.logged_in():
            subject = self.request.get("subject")
            content = Markup(markdown2.markdown(self.request.get("content")))
            last_modified = datetime.datetime.now()
            is_draft = self.request.get("is_draft")
            
            if subject and content:
                my_post = Post.get_by_id(int(post_id))
                my_post.subject = subject
                my_post.content = content
                my_post.is_draft = (is_draft == "on")
                my_post.put()

                if is_draft == "on":
                    self.redirect('/drafts')
                else:
                    memcache.flush_all()
                    self.redirect('/')
                    self.redirect('/post/' + str(my_post.key().id()))
            else:
                error = "Both subject and content please!"
                self.render("editpost.html", subject = subject, content = content, error = error)
        else:
            self.abort(403)

class DraftHandler(Handler):
    def get(self):
        posts = db.GqlQuery("SELECT * FROM Post WHERE is_draft = TRUE ORDER BY created DESC")
        self.render("main.html", posts=posts)

class DeletePostHandler(Handler):
    def get(self, post_id):
        if self.logged_in():
            my_post = Post.get_by_id(int(post_id))
            my_post.delete()
            self.redirect('/flush')
        else:
            self.abort(403)

class XMLHandler(Handler):
    def get(self):
        posts = db.GqlQuery("SELECT * FROM Post WHERE is_draft = FALSE ORDER BY created DESC")
        self.response.headers['Content-Type'] = 'application/atom+xml'
        self.render("xmltemplate.xml", posts=posts)

class FlushCacheHandler(Handler):
    def get(self):
        memcache.flush_all()
        self.redirect('/')
       
app = webapp2.WSGIApplication([('/', MainPage),
                               ('/.json', JsonPostHandler),
                               ('/blog', BlogHandler),
                               ('/post/new', NewPostHandler),
                               ('/quotes', QuotesHandler),
                               ('/login', LoginHandler),
                               ('/logout', LogoutHandler),
                               ('/post/(\d+)', ShowPostHandler),
                               ('/post/(\d+).json', ShowPostJsonHandler),
                               ('/post/(\d+)/edit', EditPostHandler),
                               ('/post/(\d+)/delete', DeletePostHandler),
                               ('/feeds/all.atom.xml', XMLHandler),
                               ('/flush', FlushCacheHandler),
                               ('/drafts',DraftHandler)], debug=True)
