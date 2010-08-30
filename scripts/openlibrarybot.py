#!/usr/bin/env python

import csv, re, urlparse
from wikitools import wiki, page, api
from optparse import OptionParser

EDIT_COMMENT = "[[Wikipedia:Bots/Requests for approval/OpenlibraryBot|discuss this trial]]"


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
    parser = OptionParser(usage="%prog [-u bot_username] [-p bot_password] file")
    parser.add_option("-u", "--bot-username", dest="bot_username", 
                      default="OpenlibraryBot",
                      help="The bot username for writing to wikipedia")
    parser.add_option("-p", "--bot-password", dest="bot_password", 
                      help="The bot password for writing to wikipedia")

    options, args = parser.parse_args()
    if len(args) != 1:
        parser.error("file required")

    if not options.bot_password:
        parser.error("bot password required")
        
    site = wiki.Wiki("http://en.wikipedia.org/w/api.php")
    site.login(options.bot_username, options.bot_password)

    def add_link(wpid, olid, type):
        p = Page(site, pageid=wpid)
        link_template = {
            "/type/author": "OL_author",
            "/type/work": "OL_work",
            "/type/book": "OL_book"
        }[type]

        # if there are no external links on the page, let's not bother, we don't
        # want to add a new section to the page
        if not p.setSection(section="External links"):
            print "%s (%s) has no external links, skipping" % (p.title, wpid)
            return

        # check if the template is used
        templates = p.getTemplates()
        if ("Template:%s" % link_template in templates or
            "Template:%s" % link_template.replace('_', ' ') in templates):
            print "%s already in %s (%s), skipping" % (link_template, p.title, wpid)
            return

        # check if there's any existing link to open library
        extlinks = p.getExternalLinks()
        extdomains = [urlparse.urlsplit(el).netloc for el in extlinks]
        if "openlibrary.org" in extdomains or "www.openlibrary.org" in extdomains:
            print "%s (%s) already links to open library, skipping" % (p.title, wpid)
            return

        old_wt = p.getWikiText()
        new_wt = insert_link_into_wikitext("{{%s|id=%s}}" % (link_template, olid), old_wt)

        if old_wt != new_wt:
            result = p.edit(bot=True, summary=EDIT_COMMENT, text=new_wt)
            assert result['edit']['result'].lower() == 'success'
            print "added %s(%s) to %s (%s)" % (link_template, olid, p.title, wpid)

    # args[0] is a tsv of [wikipediaid|openlibraryid|openlibrary_type|name (for debugging)]
    f = open(args[0])
    with f:
        data = csv.reader(f, delimiter='\t')
    
        for wpid, olid, type, name in data:
            add_link(wpid, olid, type)
