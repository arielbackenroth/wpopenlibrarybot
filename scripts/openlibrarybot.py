#!/usr/bin/env python

import csv, re, urlparse, httplib, simplejson, urllib, getpass, sys
from wikitools import wiki, page, api
from optparse import OptionParser
from termcolor import colored

class Logger:

    def warn(self, s):
        print colored("WARNING: %s" % s, 'red')

    def error(self, s):
        print >> sys.stderr, colored("ERROR: %s" % s, 'red', attrs=['blink'])

    def skip(self, s):
        print colored("SKIPPING: %s" % s, 'yellow')

LOG = Logger()

def has_readable_editions(type, olid):
    conn = httplib.HTTPConnection("openlibrary.org")
    if olid[-1] == "M" and type != "/type/book":
        LOG.warn("incorrect type for %s (%s)" % (olid, type))
        return
    if olid[-1] == "W" and type != "/type/work":
        LOG.warn("incorrect type for %s (%s)" % (olid, type))
        return
    if olid[-1] == "A" and type != "/type/author":
        LOG.warn("incorrect type for %s (%s)" % (olid, type))
        return

    try:
        if type == "/type/author":
            url = "/query.json?%s" % urllib.urlencode({
                    "type": "/type/edition",
                    "authors": "/authors/%s" % olid,
                    "ocaid": ""
            })

        elif type == "/type/work":
            url = "/query.json?%s" % urllib.urlencode({
                    "type": "/type/edition",
                    "works": "/works/%s" % olid,
                    "ocaid": ""
            })

        conn.putrequest("GET", url)
        conn.putheader("User-Agent", "wpopenlibrarybot")
        conn.endheaders()
        resp = conn.getresponse()
        if int(resp.status) != 200:
            LOG.error("error fetching %s: %s" % (url, resp.status))
        editions = simplejson.loads(resp.read())
        for edition in editions:
            if edition['ocaid']:
                return True
    finally:
        conn.close()


#EDIT_COMMENT = "[[Wikipedia:Bots/Requests for approval/OpenlibraryBot|discuss this trial]]"
EDIT_COMMENT = "/*External links*/ links to [[Open Library]]"

class Page(page.Page):

    # will get added to wikitools.page.Page...
    def getExternalLinks(self, force=False):
        """Gets a list of all the external links the page

        force - load the list even if we already loaded it before

        """
        if hasattr(self, "extlinks") and not force:
            return self.extlinks
        if self.pageid == 0 and not self.title:
            self.setPageInfo()
        if not self.exists:
            raise page.NoPage
        params = {
            'action': 'query',
            'prop': 'extlinks',
            'ellimit': self.site.limit,
        }
        if self.pageid > 0:
            params['pageids'] = self.pageid
        else:
            params['titles'] = self.title
        req = api.APIRequest(self.site, params)
        response = req.query()
        self.extlinks = []

        def _extractToList(json, stuff):
            list = []
            if self.pageid == 0:
                self.pageid = json['query']['pages'].keys()[0]
            if stuff in json['query']['pages'][str(self.pageid)]:
                # items are a single value dict of ns:link
                for item in json['query']['pages'][str(self.pageid)][stuff]:
                    list.extend(item.values())
            return list

        if isinstance(response, list): #There shouldn't be more than 5000 links on a page...
            for part in response:
                self.extlinks.extend(_extractToList(self, 'extlinks'))
        else:
            self.extlinks = _extractToList(response, 'extlinks')
        return self.extlinks

def insert_link_into_wikitext(link, wikitext):
    def generate_wikitext(lines):
        assert re.match('==\s*External links\s*==', lines[0].strip()), lines[0]
        yield lines[0]

        emptylines = []
        inserted = False
        insertable = False

        for line in lines[1:]:
            if inserted:
                # the link has been inserted - just flush remaining lines
                yield line
            elif line.strip().startswith("*"):
                # we're in something that looks like a list - we can insert the link
                # at the end
                insertable = True
                for el in emptylines:
                    yield el
                emptylines = []
                yield line
            elif not line.strip():
                # preserve whitespace
                emptylines.append(line)
            elif insertable:
                # it's not whitespace or a link - it's something else.  let's insert here
                # and then push back any whitespace
                yield "* %s" % link
                for el in emptylines:
                    yield el
                emptylines = []
                yield line
                inserted = True
            else:
                # this might be another macro like {{Wikiquotes}} - just ignore
                for el in emptylines:
                    yield el
                emptylines = []
                yield line

        if not inserted and insertable:
            # the list just ended without a newline - yield the link
            yield "* %s" % link

    return '\n'.join(list(generate_wikitext(wikitext.split('\n'))))

if __name__ == "__main__":
    parser = OptionParser(usage="%prog [-u bot_username] [-p bot_password] [-l limit] [-d --dry-run] file")
    parser.add_option("-u", "--bot-username", dest="bot_username",
                      default="OpenlibraryBot",
                      help="The bot username for writing to wikipedia")
    parser.add_option("-p", "--bot-password", dest="bot_password",
                      help="The bot password for writing to wikipedia")
    parser.add_option("-l", "--limit", dest="limit", type="int",
                      default=None,
                      help="The maximum number of links to insert")
    parser.add_option("-d", "--dry-run", dest="dry_run", action="store_true",
                      default=False,
                      help="The maximum number of links to insert")

    options, args = parser.parse_args()
    if len(args) != 1:
        parser.error("file required")

    if not options.bot_password:
        options.bot_password = getpass.getpass("Please enter the password for %s: " % options.bot_username)

    site = wiki.Wiki("http://en.wikipedia.org/w/api.php")
    site.login(options.bot_username, options.bot_password)

    def add_link(wpid, olid, type, dry_run=False):
        p = Page(site, pageid=wpid)
        link_template = {
            "/type/author": "OL_author",
            "/type/work": "OL_work",
            "/type/book": "OL_book"
        }[type]

        # if there are no external links on the page, let's not bother, we don't
        # want to add a new section to the page
        if not p.setSection(section="External links"):
            print colored("%s (%s) has no external links" % (p.title, wpid), "blue")
            return

        # check if the template is used
        templates = p.getTemplates()
        if ("Template:%s" % link_template in templates or
            "Template:%s" % link_template.replace('_', ' ') in templates):
            print colored("NOOP: %s already in %s (%s)" % (link_template, p.title, wpid), "cyan")
            return

        # check if there's any existing link to open library
        extlinks = p.getExternalLinks()
        extdomains = [urlparse.urlsplit(el).netloc for el in extlinks]
        if "openlibrary.org" in extdomains or "www.openlibrary.org" in extdomains:
            print colored("NOOP: %s (%s) already links to open library" % (p.title, wpid), "cyan")
            return

        old_wt = p.getWikiText()
        new_wt = insert_link_into_wikitext("{{%s|id=%s}}" % (link_template, olid), old_wt)

        if old_wt != new_wt:
            print "Confirm adding link from \n\t%s to \n\t%s (y|n)" % (
                "http://en.wikipedia.org/wiki/index.html?curid=%s" % wpid,
                "http://openlibrary.org/%s/%s" % (
                    {"A": "authors", "W": "works", "M": "books"}[olid[-1]],
                    olid
                )
            )

            while True:
                answer = sys.stdin.readline().strip()
                if answer not in ('y', 'n'):
                    continue
                if answer == 'n':
                    return
                else:
                    break

            if not dry_run:
                result = p.edit(bot=True, summary=EDIT_COMMENT, text=new_wt)
                assert result['edit']['result'].lower() == 'success'
            print colored("added %s(%s) to %s (%s)" % (link_template, olid, p.title, wpid), "green")
            return True

    # args[0] is a tsv of [wikipediaid|openlibraryid|openlibrary_type|name (for debugging)]
    f = open(args[0])
    num_added = 0
    with f:
        data = csv.reader(f, delimiter='\t')

        for wpid, olid, type, name in data:
            if options.limit is not None and num_added >= options.limit:
                break
            if has_readable_editions(type, olid):
                print "%s (%s, %s) has readable editions" % (name, olid, wpid)
                added = add_link(wpid, olid, type, dry_run=options.dry_run)
                if added:
                    num_added += 1
            else:
                LOG.skip("%s (%s) has no readable editions" % (name, olid))
    print colored("added %s links.  done" % num_added, 'blue')
