from lxml import etree
import pkg_resources
import logging

from xmodule.modulestore import Location

from functools import partial

log = logging.getLogger('mitx.' + __name__)


def dummy_track(event_type, event):
    pass


class ModuleMissingError(Exception):
    pass


class Plugin(object):
    """
    Base class for a system that uses entry_points to load plugins.

    Implementing classes are expected to have the following attributes:

        entry_point: The name of the entry point to load plugins from
    """

    _plugin_cache = None

    @classmethod
    def load_class(cls, identifier, default=None):
        """
        Loads a single class instance specified by identifier. If identifier
        specifies more than a single class, then logs a warning and returns the
        first class identified.

        If default is not None, will return default if no entry_point matching
        identifier is found. Otherwise, will raise a ModuleMissingError
        """
        if cls._plugin_cache is None:
            cls._plugin_cache = {}

        if identifier not in cls._plugin_cache:
            identifier = identifier.lower()
            classes = list(pkg_resources.iter_entry_points(
                    cls.entry_point, name=identifier))

            if len(classes) > 1:
                log.warning("Found multiple classes for {entry_point} with "
                            "identifier {id}: {classes}. "
                            "Returning the first one.".format(
                    entry_point=cls.entry_point,
                    id=identifier,
                    classes=", ".join(
                            class_.module_name for class_ in classes)))

            if len(classes) == 0:
                if default is not None:
                    return default
                raise ModuleMissingError(identifier)

            cls._plugin_cache[identifier] = classes[0].load()
        return cls._plugin_cache[identifier]

    @classmethod
    def load_classes(cls):
        return [class_.load()
                for class_
                in pkg_resources.iter_entry_points(cls.entry_point)]


class HTMLSnippet(object):
    """
    A base class defining an interface for an object that is able to present an
    html snippet, along with associated javascript and css
    """

    js = {}
    js_module_name = None

    css = {}

    @classmethod
    def get_javascript(cls):
        """
        Return a dictionary containing some of the following keys:

            coffee: A list of coffeescript fragments that should be compiled and
                    placed on the page

            js: A list of javascript fragments that should be included on the
            page

        All of these will be loaded onto the page in the CMS
        """
        return cls.js

    @classmethod
    def get_css(cls):
        """
        Return a dictionary containing some of the following keys:

            css: A list of css fragments that should be applied to the html
                 contents of the snippet

            sass: A list of sass fragments that should be applied to the html
                  contents of the snippet

            scss: A list of scss fragments that should be applied to the html
                  contents of the snippet
        """
        return cls.css

    def get_html(self):
        """
        Return the html used to display this snippet
        """
        raise NotImplementedError(
            "get_html() must be provided by specific modules - not present in {0}"
                                  .format(self.__class__))


class XModule(HTMLSnippet):
    ''' Implements a generic learning module.

        Subclasses must at a minimum provide a definition for get_html in order
        to be displayed to users.

        See the HTML module for a simple example.
    '''

    # The default implementation of get_icon_class returns the icon_class
    # attribute of the class
    #
    # This attribute can be overridden by subclasses, and
    # the function can also be overridden if the icon class depends on the data
    # in the module
    icon_class = 'other'

    def __init__(self, system, location, definition,
                 instance_state=None, shared_state=None, **kwargs):
        '''
        Construct a new xmodule

        system: A ModuleSystem allowing access to external resources

        location: Something Location-like that identifies this xmodule

        definition: A dictionary containing 'data' and 'children'. Both are
        optional

            'data': is JSON-like (string, dictionary, list, bool, or None,
                optionally nested).

                This defines all of the data necessary for a problem to display
                that is intrinsic to the problem.  It should not include any
                data that would vary between two courses using the same problem
                (due dates, grading policy, randomization, etc.)

            'children': is a list of Location-like values for child modules that
                this module depends on

        instance_state: A string of serialized json that contains the state of
                this module for current student accessing the system, or None if
                no state has been saved

        shared_state: A string of serialized json that contains the state that
            is shared between this module and any modules of the same type with
            the same shared_state_key. This state is only shared per-student,
            not across different students

        kwargs: Optional arguments. Subclasses should always accept kwargs and
            pass them to the parent class constructor.

            Current known uses of kwargs:

                metadata: SCAFFOLDING - This dictionary will be split into
                    several different types of metadata in the future (course
                    policy, modification history, etc).  A dictionary containing
                    data that specifies information that is particular to a
                    problem in the context of a course
        '''
        self.system = system
        self.location = Location(location)
        self.definition = definition
        self.instance_state = instance_state
        self.shared_state = shared_state
        self.id = self.location.url()
        self.name = self.location.name
        self.category = self.location.category
        self.metadata = kwargs.get('metadata', {})
        self._loaded_children = None

    def get_name(self):
        return self.name

    def get_children(self):
        '''
        Return module instances for all the children of this module.
        '''
        if self._loaded_children is None:
            self._loaded_children = [
                self.system.get_module(child)
                for child in self.definition.get('children', [])]

        return self._loaded_children

    def get_display_items(self):
        '''
        Returns a list of descendent module instances that will display
        immediately inside this module
        '''
        items = []
        for child in self.get_children():
            items.extend(child.displayable_items())

        return items

    def displayable_items(self):
        '''
        Returns list of displayable modules contained by this module. If this
        module is visible, should return [self]
        '''
        return [self]

    def get_icon_class(self):
        '''
        Return a css class identifying this module in the context of an icon
        '''
        return self.icon_class

    ### Functions used in the LMS

    def get_instance_state(self):
        ''' State of the object, as stored in the database
        '''
        return '{}'

    def get_shared_state(self):
        '''
        Get state that should be shared with other instances
        using the same 'shared_state_key' attribute.
        '''
        return '{}'

    def get_score(self):
        ''' Score the student received on the problem.
        '''
        return None

    def max_score(self):
        ''' Maximum score. Two notes:

            * This is generic; in abstract, a problem could be 3/5 points on one
              randomization, and 5/7 on another

            * In practice, this is a Very Bad Idea, and (a) will break some code
              in place (although that code should get fixed), and (b) break some
              analytics we plan to put in place.
        '''
        return None

    def get_progress(self):
        ''' Return a progress.Progress object that represents how far the
        student has gone in this module.  Must be implemented to get correct
        progress tracking behavior in nesting modules like sequence and
        vertical.

        If this module has no notion of progress, return None.
        '''
        return None

    def handle_ajax(self, dispatch, get):
        ''' dispatch is last part of the URL.
            get is a dictionary-like object '''
        return ""


class XModuleDescriptor(Plugin, HTMLSnippet):
    """
    An XModuleDescriptor is a specification for an element of a course. This
    could be a problem, an organizational element (a group of content), or a
    segment of video, for example.

    XModuleDescriptors are independent and agnostic to the current student state
    on a problem. They handle the editing interface used by instructors to
    create a problem, and can generate XModules (which do know about student
    state).
    """
    entry_point = "xmodule.v1"
    module_class = XModule

    # A list of metadata that this module can inherit from its parent module
    inheritable_metadata = (
        'graded', 'start', 'due', 'graceperiod', 'showanswer', 'rerandomize',

        # TODO: This is used by the XMLModuleStore to provide for locations for
        # static files, and will need to be removed when that code is removed
        'data_dir'
    )

    # A list of descriptor attributes that must be equal for the descriptors to
    # be equal
    equality_attributes = ('definition', 'metadata', 'location',
                           'shared_state_key', '_inherited_metadata')

    # ============================= STRUCTURAL MANIPULATION ===================
    def __init__(self,
                 system,
                 definition=None,
                 **kwargs):
        """
        Construct a new XModuleDescriptor. The only required arguments are the
        system, used for interaction with external resources, and the
        definition, which specifies all the data needed to edit and display the
        problem (but none of the associated metadata that handles recordkeeping
        around the problem).

        This allows for maximal flexibility to add to the interface while
        preserving backwards compatibility.

        system: A DescriptorSystem for interacting with external resources

        definition: A dict containing `data` and `children` representing the
        problem definition

        Current arguments passed in kwargs:

            location: A xmodule.modulestore.Location object indicating the name
                and ownership of this problem

            shared_state_key: The key to use for sharing StudentModules with
                other modules of this type

            metadata: A dictionary containing the following optional keys:
                goals: A list of strings of learning goals associated with this
                    module
                display_name: The name to use for displaying this module to the
                    user
                format: The format of this module ('Homework', 'Lab', etc)
                graded (bool): Whether this module is should be graded or not
                start (string): The date for which this module will be available
                due (string): The due date for this module
                graceperiod (string): The amount of grace period to allow when
                    enforcing the due date
                showanswer (string): When to show answers for this module
                rerandomize (string): When to generate a newly randomized
                    instance of the module data
        """
        self.system = system
        self.metadata = kwargs.get('metadata', {})
        self.definition = definition if definition is not None else {}
        self.location = Location(kwargs.get('location'))
        self.name = self.location.name
        self.category = self.location.category
        self.shared_state_key = kwargs.get('shared_state_key')

        self._child_instances = None
        self._inherited_metadata = set()

    def inherit_metadata(self, metadata):
        """
        Updates this module with metadata inherited from a containing module.
        Only metadata specified in self.inheritable_metadata will
        be inherited
        """
        # Set all inheritable metadata from kwargs that are
        # in self.inheritable_metadata and aren't already set in metadata
        for attr in self.inheritable_metadata:
            if attr not in self.metadata and attr in metadata:
                self._inherited_metadata.add(attr)
                self.metadata[attr] = metadata[attr]

    def get_children(self):
        """Returns a list of XModuleDescriptor instances for the children of
        this module"""
        if self._child_instances is None:
            self._child_instances = []
            for child_loc in self.definition.get('children', []):
                child = self.system.load_item(child_loc)
                child.inherit_metadata(self.metadata)
                self._child_instances.append(child)

        return self._child_instances

    def xmodule_constructor(self, system):
        """
        Returns a constructor for an XModule. This constructor takes two
        arguments: instance_state and shared_state, and returns a fully
        instantiated XModule
        """
        return partial(
            self.module_class,
            system,
            self.location,
            self.definition,
            metadata=self.metadata
        )

    # ================================= JSON PARSING ===========================
    @staticmethod
    def load_from_json(json_data, system, default_class=None):
        """
        This method instantiates the correct subclass of XModuleDescriptor based
        on the contents of json_data.

        json_data must contain a 'location' element, and must be suitable to be
        passed into the subclasses `from_json` method.
        """
        class_ = XModuleDescriptor.load_class(
            json_data['location']['category'],
            default_class
        )
        return class_.from_json(json_data, system)

    @classmethod
    def from_json(cls, json_data, system):
        """
        Creates an instance of this descriptor from the supplied json_data.
        This may be overridden by subclasses

        json_data: A json object specifying the definition and any optional
            keyword arguments for the XModuleDescriptor

        system: A DescriptorSystem for interacting with external resources
        """
        return cls(system=system, **json_data)

    # ================================= XML PARSING ============================
    @staticmethod
    def load_from_xml(xml_data,
            system,
            org=None,
            course=None,
            default_class=None):
        """
        This method instantiates the correct subclass of XModuleDescriptor based
        on the contents of xml_data.

        xml_data must be a string containing valid xml

        system is an XMLParsingSystem

        org and course are optional strings that will be used in the generated
            modules url identifiers
        """
        class_ = XModuleDescriptor.load_class(
            etree.fromstring(xml_data).tag,
            default_class
        )
        # leave next line, commented out - useful for low-level debugging
        # log.debug('[XModuleDescriptor.load_from_xml] tag=%s, class_=%s' % (
        #        etree.fromstring(xml_data).tag,class_))
        return class_.from_xml(xml_data, system, org, course)

    @classmethod
    def from_xml(cls, xml_data, system, org=None, course=None):
        """
        Creates an instance of this descriptor from the supplied xml_data.
        This may be overridden by subclasses

        xml_data: A string of xml that will be translated into data and children
            for this module

        system is an XMLParsingSystem

        org and course are optional strings that will be used in the generated
            module's url identifiers
        """
        raise NotImplementedError(
            'Modules must implement from_xml to be parsable from xml')

    def export_to_xml(self, resource_fs):
        """
        Returns an xml string representing this module, and all modules
        underneath it.  May also write required resources out to resource_fs

        Assumes that modules have single parentage (that no module appears twice
        in the same course), and that it is thus safe to nest modules as xml
        children as appropriate.

        The returned XML should be able to be parsed back into an identical
        XModuleDescriptor using the from_xml method with the same system, org,
        and course
        """
        raise NotImplementedError(
            'Modules must implement export_to_xml to enable xml export')

    # =============================== Testing ==================================
    def get_sample_state(self):
        """
        Return a list of tuples of instance_state, shared_state. Each tuple
        defines a sample case for this module
        """
        return [('{}', '{}')]

    # =============================== BUILTIN METHODS ==========================
    def __eq__(self, other):
        eq = (self.__class__ == other.__class__ and
                all(getattr(self, attr, None) == getattr(other, attr, None)
                    for attr in self.equality_attributes))

        # if not eq:
        #     for attr in self.equality_attributes:
        #         print(getattr(self, attr, None),
        #               getattr(other, attr, None),
        #               getattr(self, attr, None) == getattr(other, attr, None))

        return eq

    def __repr__(self):
        return ("{class_}({system!r}, {definition!r}, location={location!r},"
                " metadata={metadata!r})".format(
            class_=self.__class__.__name__,
            system=self.system,
            definition=self.definition,
            location=self.location,
            metadata=self.metadata
        ))


class DescriptorSystem(object):
    def __init__(self, load_item, resources_fs, error_handler):
        """
        load_item: Takes a Location and returns an XModuleDescriptor

        resources_fs: A Filesystem object that contains all of the
            resources needed for the course

        error_handler: A hook for handling errors in loading the descriptor.
            Must be a function of (error_msg, exc_info=None).
            See errorhandlers.py for some simple ones.

            Patterns for using the error handler:
               try:
                  x = access_some_resource()
                  check_some_format(x)
               except SomeProblem:
                  msg = 'Grommet {0} is broken'.format(x)
                  log.exception(msg) # don't rely on handler to log
                  self.system.error_handler(msg)
                  # if we get here, work around if possible
                  raise # if no way to work around
                       OR
                  return 'Oops, couldn't load grommet'

               OR, if not in an exception context:

               if not check_something(thingy):
                  msg = "thingy {0} is broken".format(thingy)
                  log.critical(msg)
                  error_handler(msg)
                  # if we get here, work around
                  pass   # e.g. if no workaround needed
        """

        self.load_item = load_item
        self.resources_fs = resources_fs
        self.error_handler = error_handler


class XMLParsingSystem(DescriptorSystem):
    def __init__(self, load_item, resources_fs, error_handler, process_xml):
        """
        load_item, resources_fs, error_handler: see DescriptorSystem

        process_xml: Takes an xml string, and returns a XModuleDescriptor
            created from that xml
        """
        DescriptorSystem.__init__(self, load_item, resources_fs, error_handler)
        self.process_xml = process_xml


class ModuleSystem(object):
    '''
    This is an abstraction such that x_modules can function independent
    of the courseware (e.g. import into other types of courseware, LMS,
    or if we want to have a sandbox server for user-contributed content)

    ModuleSystem objects are passed to x_modules to provide access to system
    functionality.

    Note that these functions can be closures over e.g. a django request
    and user, or other environment-specific info.
    '''
    def __init__(self, ajax_url, track_function,
                 get_module, render_template, replace_urls,
                 user=None, filestore=None, debug=False,
                 xqueue_callback_url=None):
        '''
        Create a closure around the system environment.

        ajax_url - the url where ajax calls to the encapsulating module go.

        track_function - function of (event_type, event), intended for logging
                         or otherwise tracking the event.
                         TODO: Not used, and has inconsistent args in different
                         files.  Update or remove.

        get_module - function that takes (location) and returns a corresponding
                         module instance object.

        render_template - a function that takes (template_file, context), and
                         returns rendered html.

        user - The user to base the random number generator seed off of for this
                         request

        filestore - A filestore ojbect.  Defaults to an instance of OSFS based
                         at settings.DATA_DIR.

        replace_urls - TEMPORARY - A function like static_replace.replace_urls
                         that capa_module can use to fix up the static urls in
                         ajax results.
        '''
        self.ajax_url = ajax_url
        self.xqueue_callback_url = xqueue_callback_url
        self.track_function = track_function
        self.filestore = filestore
        self.get_module = get_module
        self.render_template = render_template
        self.DEBUG = self.debug = debug
        self.seed = user.id if user is not None else 0
        self.replace_urls = replace_urls

    def get(self, attr):
        '''	provide uniform access to attributes (like etree).'''
        return self.__dict__.get(attr)

    def set(self, attr, val):
        '''provide uniform access to attributes (like etree)'''
        self.__dict__[attr] = val

    def __repr__(self):
        return repr(self.__dict__)

    def __str__(self):
        return str(self.__dict__)
