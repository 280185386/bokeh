from __future__ import print_function

from ..server import start
from threading import Thread

class Server(object):
    """Runs a server which displays an in-process document"""

    def __init__(self, **kwargs):
        self.docid = None

        self.port = 5006
        if 'port' in kwargs:
            self.port = kwargs['port']

        self._listen_server(port=self.port)
        self.appname = 'bokeh-app'
        if 'appname' in kwargs:
            self.appname = kwargs['appname']

        # this is probably pretty evil and not safe if there are any
        # globals shared between the bokeh server and client code,
        # which I think there are. The right fix may be to have an
        # alternative to output_server that works in-process?
        self.thread = Thread(target=self._background_server)
        self.thread.start()

        self._create_document()

    def document_link(self, doc):
        return "http://localhost:%d/bokeh/doc/%s/%s" % (self.port, self.docid, doc.context._id)

    def push(self, doc, dirty_only=True):
        """Push changes to the document to the client"""

        ## cut and paste from bokeh.server to avoid REST
        from ..server.models import docs
        from ..server.app import bokeh_app
        from ..server.serverbb import BokehServerTransaction
        from ..server.views.backbone import ws_update
        from .. import protocol

        doc._add_all()
        models = doc._models.values()

        if dirty_only:
            models = [x for x in models if getattr(x, '_dirty', False)]

        if len(models) < 1:
            return

        # TODO clearly serializing to json here is absurd
        json = protocol.serialize_json(doc.dump(*models))
        data = protocol.deserialize_json(json.decode('utf-8'))

        for model in models:
            model._dirty = False

        docid = self.docid
        server_doc = docs.Doc.load(bokeh_app.servermodel_storage, docid)
        bokehuser = bokeh_app.current_user()
        temporary_docid = None #str(uuid.uuid4())
        t = BokehServerTransaction(
            bokehuser, server_doc, 'rw', temporary_docid=temporary_docid
        )
        t.load()
        clientdoc = t.clientdoc
        clientdoc.load(*data, events='none', dirty=True)
        t.save()
        ws_update(clientdoc, t.write_docid, t.changed)

    def waitFor(self):
        """Block until server shuts down"""
        # thread.join isn't actually interruptable
        # which currently prevents ctrl-C and is annoying
        self.thread.join()

    def stop(self):
        """Shut down the server"""
        self._stop_server()

    # this is a cut-and-paste from bokeh.server in order to
    # start the main loop separately
    def _listen_server(self, port=-1, args=None):
        from ..server.start import create_listening_server
        from ..server.settings import settings as server_settings
        from ..server.configure import configure_flask

        configure_flask(config_argparse=args)
        if port >= 0:
            server_settings.port = port
        self.server = create_listening_server()

    def _background_server(self):
        start.start(server=self.server)

    def _stop_server(self):
        start.stop(server=self.server)

    # cut-and-paste from bokeh.server to avoid going through REST
    def _create_document(self):
        from ..server.app import bokeh_app
        from ..server.views.main import _makedoc # naughty
        from ..server.models import docs
        from ..server.serverbb import BokehServerTransaction
        from ..io import curdoc
        from .. import protocol

        user = bokeh_app.current_user()
        existing = filter(lambda x: x['title'] == self.appname, user.docs)
        if len(existing) > 0:
            self.docid = existing[0]['docid']
        else:
            doc = _makedoc(bokeh_app.servermodel_storage, user, self.appname)
            self.docid = doc.docid

        docid = self.docid
        server_doc = docs.Doc.load(bokeh_app.servermodel_storage, docid)
        temporary_docid = None #str(uuid.uuid4())
        t = BokehServerTransaction(
            user, server_doc, 'rw', temporary_docid=None,
        )
        t.load()
        clientdoc = t.clientdoc
        all_models = clientdoc._models.values()
        # TODO clearly serializing to json here is absurd
        json = protocol.serialize_json(clientdoc.dump(*all_models))
        attrs = protocol.deserialize_json(json.decode('utf-8'))
        curdoc().merge(attrs)
