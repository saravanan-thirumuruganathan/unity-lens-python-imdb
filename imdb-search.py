#! /usr/bin/python
#For more details see
#	1. https://wiki.ubuntu.com/Unity/Lenses
#	2. Tutorial at http://saravananthirumuruganathan.wordpress.com/2011/08/05/tutorial-on-writing-ubuntu-lensesplaces-in-python/ .

import sys
import imdb

from gi.repository import GLib, GObject, Gio, Dee, Unity

# This is the DBUS name that we are going to use for communication. 
# 	Make sure that this name exactly matches with the one in your .place file (entry for DBusName).
BUS_NAME = "net.launchpad.IMDBSearchLens"


# Sections in your lens. These constants are primarily used to figure out which is the current active section.
#	This means when you synchonize your sections, the order of sections in the model must *exactly* match this order
#		ie SECTION_NAME_ONLY before SECTION_GENRE_INFO 
SECTION_NAME_ONLY = 0
SECTION_GENRE_INFO = 1

# Group  in your lens. You can either have constants for group names similar to how we did for sections above.
#	The constants are used when we want to add an entry to the appropriate group.
#	This means when you synchonize your groups, the order of groups in the model must *exactly* match this order
#Note :
#	1. Same item can be in different grups
#	2. The order of your groups is how the results will be showed. Eg entries in group 0 before group 1 and so on.
#	3. If section1 uses gp1,gp2 and section2 uses gp2,gp3 then declar all gp1,gp2,gp3 and in code assign entries appropriately.
#	4. It is preferrable to have a group for no results.

#This is an example of code having groups that does not have equivalent constants. Instead we have a hash that links genre name with group id.
#Note that we have GROUP_EMPTY for no results and GROUP_MOVIE_NAMES_ONLY that corresponds to SECTION_NAME_ONLY.
allGenreGroupNames = [ "Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary", "Drama", "Family",	"Fantasy", "Film-Noir",	"Game-Show", "History",	"Horror", "Music",  "Musical", "Mystery", "News", "Reality-TV", "Romance", "Sci-Fi", "Sport", "Talk-Show", "Thriller", "War", "Western"]

numGenreGroups = len(allGenreGroupNames)
GROUP_EMPTY = numGenreGroups
GROUP_MOVIE_NAMES_ONLY = numGenreGroups + 1
GROUP_OTHER = numGenreGroups + 2

groupNameTogroupId = {}
#We create a hash which allows to find the group name from genre.
for i in range(len(allGenreGroupNames)):
	groupName = allGenreGroupNames[i]
	groupID = i 
	groupNameTogroupId[groupName] = groupID

class Daemon:
	def __init__ (self):
		# This is the path for our DBUS name that we are going to use for communication. 
		# 	Make sure that this name exactly matches with the one in your .place file (entry for DBusObjectPath).
		self._entry = Unity.PlaceEntryInfo.new ("/net/launchpad/imdbsearchlens/mainentry")
		
		#
		# Set up all the datamodels we'll share with the Unity process
		# See https://wiki.ubuntu.com/Unity/Lenses for additional details.
		#
		# Terminology:
		#
		#   - "sections" A set of disjoint browsable categories.
		#                Fx. "Books", "Film", and "Music"
		#
		#   - "groups" A set of labels that partition the result set into
		#              user-visible chunks. "Popular Books", "Most Recent Books" 
		#

		#set_schema("s","s") corresponds to display name for section , the icon used to display
		sections_model = Dee.SharedModel.new (BUS_NAME + ".SectionsModel");
		sections_model.set_schema ("s", "s");
		self._entry.props.sections_model = sections_model

		#set_schema("s","s") corresponds to renderer used to display group, display name for group , the icon used to display
		groups_model = Dee.SharedModel.new (BUS_NAME + ".GroupsModel");
		groups_model.set_schema ("s", "s", "s");
		self._entry.props.entry_renderer_info.props.groups_model = groups_model

		#Same as above
		global_groups_model = Dee.SharedModel.new (BUS_NAME + ".GlobalGroupsModel");
		global_groups_model.set_schema ("s", "s", "s");
		self._entry.props.global_renderer_info.props.groups_model = global_groups_model

		#set_schema(s,s,u,s,s,s) corresponds to URI, Icon name, Group id, MIME type, display name for entry, comment
		results_model = Dee.SharedModel.new (BUS_NAME + ".ResultsModel");
		results_model.set_schema ("s", "s", "u", "s", "s", "s");
		self._entry.props.entry_renderer_info.props.results_model = results_model

		#Same as above
		global_results_model = Dee.SharedModel.new (BUS_NAME + ".GlobalResultsModel");
		global_results_model.set_schema ("s", "s", "u", "s", "s", "s");
		self._entry.props.global_renderer_info.props.results_model = global_results_model

		# Populate the sections and groups once we are in sync with Unity
		sections_model.connect ("notify::synchronized", self._on_sections_synchronized)
		groups_model.connect ("notify::synchronized", self._on_groups_synchronized)

		#Comment the next line if you do not want your lens to be searched in dash
		global_groups_model.connect ("notify::synchronized", self._on_global_groups_synchronized)

		# Set up the signals we'll receive when Unity starts to talk to us

		# The 'active-search' property is changed when the users searches within this particular place
		self._entry.connect ("notify::active-search", self._on_search_changed)
		
		# The 'active-global-search' property is changed when the users searches from the Dash aka Home Screen
		#	Every place can provide results for the search query.

		#Comment the next line if you do not want your lens to be searched in dash
		self._entry.connect ("notify::active-global-search", self._on_global_search_changed)

		# Listen for changes to the section.
		self._entry.connect("notify::active-section", self._on_section_change)

		# Listen for changes to the status - Is our place active or hidden?
		self._entry.connect("notify::active", self._on_active_change)

		
		#
		# PlaceEntries are housed by PlaceControllers.
		# You may have mutiple entries per controller if you like.
		# The controller *must* have the DBus Object path you specify
		# in your .place file
		#
		self._ctrl = Unity.PlaceController.new ("/net/launchpad/imdbsearchlens")		
		self._ctrl.add_entry (self._entry)
		self._ctrl.export ()

		self.ia = imdb.IMDb()

		#Since getting IMDB movie details is an expensive operation,
		#	the results are stored in a cache
		#for alternate approaches like memoize_indefinitely , check out the blog post.
		#Reason to use custon cache is because most implementations of memoize work by
		#	memoizing function results using the arguments which does not really 
		#	fit here.
		self.movieIMDBDtlsCache = {}

	#This function returns the search query typed in the lens
	def get_search_string (self):
		search = self._entry.props.active_search
		print "in get_search_string and search is " , search
		return search.get_search_string() if search else None
	
	#This function returns the search query typed in the dash which is passed to our lens
	def get_global_search_string (self):
		search = self._entry.props.active_global_search
		print "in get_global_search_string and search is " , search
		return search.get_search_string() if search else None
	
	#Signal to the lens/dash that we are done with the search initiated from our lens
	def search_finished (self):
		search = self._entry.props.active_search
		print "in search_finished and search is " , search
		if search:
			#Signal completion of search
			search.finished ()
	
	#Signal to the lens/dash that we are done with the search initiated from dash
	def global_search_finished (self):
		search = self._entry.props.active_global_search
		print "in global_search_finished and search is " , search
		if search:
			#Signal completion of search
			search.finished()
	
	def _on_sections_synchronized (self, sections_model, *args):
		# Column0: display name
		# Column1: GIcon in string format. Or you can pass entire path (or use GIcon).
		sections_model.clear ()
		sections_model.append ("Movie Names", Gio.ThemedIcon.new ("video").to_string())
		sections_model.append ("Movie Genre", Gio.ThemedIcon.new ("video").to_string())
	
	def _on_groups_synchronized (self, groups_model, *args):
		# Column0: group renderer
		# Column1: display name
		# Column2: GIcon in string format Or you can pass entire path (or use GIcon).
		groups_model.clear ()


		#Remember to add groups in the order you defined above (ie when defining constants)

		# For same search query, two sections can return different entries. 
		#	If one of the sections returns 0 results while other returns more 
		#	then you can highlight that 0 results are due to the section. 
		#	If you decide to make that distinction , make use of UnityEmptySectionRenderer
		#	Else stick with either UnityDefaultRenderer or UnityHorizontalTileRenderer
		#If you want to highlight that the search returned zero results then use UnityEmptySearchRenderer
		for groupName in allGenreGroupNames:
			groups_model.append ("UnityHorizontalTileRenderer", groupName, Gio.ThemedIcon.new ("sound").to_string())
		#GROUP_EMPTY
		groups_model.append ("UnityEmptySearchRenderer", "No results found from IMDB", Gio.ThemedIcon.new ("sound").to_string())
		#GROUP_MOVIE_NAMES_ONLY
		groups_model.append ("UnityHorizontalTileRenderer", "Movie Names", Gio.ThemedIcon.new ("sound").to_string())
		#GROUP_OTHER
		groups_model.append ("UnityHorizontalTileRenderer", "Other", Gio.ThemedIcon.new ("sound").to_string())

	#Here we reuse the same sections in our lens. Potentially, it can be different.
	def _on_global_groups_synchronized (self, global_groups_model, *args):
		# Just the same as the normal groups
		self._on_groups_synchronized (global_groups_model)

	#This function is called when any change is search query is made . There are two signatures :
	#	_on_search_changed(self,*args)
	#	_on_search_changed(self,entry,*args)
	# In our case, since we store the entry data in self._entry , we use the first.
	def _on_search_changed (self, *args):		
		entry = self._entry
		#Get which section the lens is in.
		self.active_section = entry.get_property("active-section")

		search = self.get_search_string()

		#Notice that due GI, all the objects are property based. There are two ways to access data.
		#	g.get_property("blah")
		#	g.props.blah

		#For eg 
		#	results = self._entry.get_property("entry_renderer_info").get_property("results_model")
		#	results = self._entry.props.entry_renderer_info.props.results_model

		# In the code we use the later.
		results = self._entry.props.entry_renderer_info.props.results_model
		
		print "Search changed to: '%s'" % search
		
		self._update_results_model (search, results)
		#Signal completion of search
		self.search_finished()
	
	def _on_global_search_changed (self, entry, param_spec):
		self.active_section = entry.get_property("active-section")
		search = self.get_global_search_string()
		results = self._entry.props.global_renderer_info.props.results_model
		
		print "Global search changed to: '%s'" % search
		
		self._update_results_model (search, results)
		#Signal completion of search
		self.global_search_finished()
	
	#Gives the information whether our lens is visible or not.
	#	Works most of the time. 
	#	May be, You can use this information to stop results if lens is not displayed?
	def _on_active_change(self, entry, section):
		print "on_active_change"

	#Called when the user changes the section 
	#This code runs the search for the query that is currently in the lens.
	def _on_section_change(self, entry, section):
		#This is an integer . use the SECTION_* constants to figure out which section.
		self.active_section = entry.get_property("active-section")
		print "on_section_change and new section is ", self.active_section
		search = self.get_search_string()
		results = self._entry.props.global_renderer_info.props.results_model
		if search:
			self._update_results_model (search, results)
			self.search_finished()
	
	#Heart of the Lens. Does the IMDB search.
	#For efficiency :
	#	Waits for atleast 4 characters before initiating search
	#	When searching for genre information (which is an expensive operation), it stores the results in a cache 
	#		self.movieIMDBDtlsCache
	def _update_results_model (self, search, model):
		if search == None:
			return 

		if len(search) < 4:
			print "Not performing as search < 4 characters"
			return 
		self.active_section = self._entry.get_property("active-section")


		model.clear ()
		model.flush_revision_queue()

		print "Going to search for ", search

		allMovieResults = self.ia.search_movie(search)
		icon_hint = Gio.ThemedIcon.new ("video").to_string()

		#If no results in IMDB, show empty group using UnityEmptySearchRenderer .
		if len(allMovieResults) == 0:
			model.append("", icon_hint , GROUP_EMPTY, "text/html", "Your search did not match anything.", "No results found")
			return 

		print "Got totally " , len(allMovieResults) , " results for search query ", search

		#Else for each movie item ,check if it is in cache. 
		#	If so use it
		#	Else get details from IMDB and put it in cache.

		#For extra responsiveness, flush details every 5 movies !
		numMoviesProcessed = 0
		for movieItem in allMovieResults:
			movieName = movieItem['long imdb canonical title']
			movieID = movieItem.movieID
			if self.active_section == SECTION_NAME_ONLY :
				group = GROUP_MOVIE_NAMES_ONLY
				#uri, GIcon/GThemedIcon, group id, mime type, display name, comment
				model.append ("http://www.imdb.com/title/tt" + movieID, icon_hint, group,                                  
					      "text/html", movieName, "See details of '%s' in IMDB" % movieName) 
			elif self.active_section == SECTION_GENRE_INFO :
				imdbDtlsOfMovie = self.movieIMDBDtlsCache.get(movieID,None) 
				if imdbDtlsOfMovie == None:
					print "Details of ", movieName , " not in cache. Querying IMDB"

					#ia.update(item,"main") gets most details. 
					#	Some info like plot are ignored.
					self.ia.update(movieItem,"main")
					genres = movieItem.get("genres",[])
					self.movieIMDBDtlsCache[movieID] = movieItem
				else:
					genres = imdbDtlsOfMovie.get("genres",[])
					print "Got details of ", movieName , " from cache"
				#By now we got from the cache.
				if genres == []:
					print "Ignoring " , movieItem , " as it has no genre"
					continue

				#If movie has k genre, add the movie to all k genre groups.
				#Use groupNameTogroupId hash to map genre to group id constant.
				for genre in genres:
					group = groupNameTogroupId.get(genre, GROUP_OTHER)
					#uri, GIcon/GThemedIcon, group id, mime type, display name, comment
					model.append ("http://www.imdb.com/title/tt" + movieID, icon_hint, group,                                  
						      "text/html", movieName, "See details of '%s' in IMDB" % movieName) 
			else:
				pass
			numMoviesProcessed = numMoviesProcessed + 1
			if numMoviesProcessed % 5 == 0 :
				model.flush_revision_queue()

		#Flush final set of results.
		model.flush_revision_queue()
			

if __name__ == "__main__":
	# NOTE: If we used the normal 'dbus' module for Python we'll get
	#       slightly odd results because it uses a default connection
	#       to the session bus that is different from the default connection
	#       GDBus (hence libunity) will use. Meaning that the daemon name
	#       will be owned by a connection different from the one all our
	#       Dee + Unity magic is working on...
	#       Still waiting for nice GDBus bindings to land:
	#                        http://www.piware.de/2011/01/na-zdravi-pygi/


	# --------- Not sure if this still relevant ---- sara
	
	session_bus_connection = Gio.bus_get_sync (Gio.BusType.SESSION, None)
	session_bus = Gio.DBusProxy.new_sync (session_bus_connection, 0, None, 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', None)
	result = session_bus.call_sync('RequestName', GLib.Variant ("(su)", (BUS_NAME, 0x4)), 0, -1, None)
	                               
	# Unpack variant response with signature "(u)". 1 means we got it.
	result = result.unpack()[0]
	
	if result != 1 :
		print >> sys.stderr, "Failed to own name %s. Bailing out." % BUS_NAME
		raise SystemExit (1)
	
	daemon = Daemon()
	GObject.MainLoop().run()

