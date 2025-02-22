import json
import os
import time
from shutil import rmtree
from subprocess import call
from threading import Thread

from django.conf import settings
from django.template import engines
from django.template.backends.django import Template
from django.template.response import TemplateResponse
from django.test.client import RequestFactory
from django.test.testcases import TestCase
from django.views.generic.base import TemplateView
from django_jinja.builtins import DEFAULT_EXTENSIONS

from webpack_loader.exceptions import (WebpackBundleLookupError, WebpackError,
                                       WebpackLoaderBadStatsError,
                                       WebpackLoaderTimeoutError)
from webpack_loader.utils import get_loader

BUNDLE_PATH = os.path.join(
    settings.BASE_DIR, 'assets/django_webpack_loader_bundles/')
DEFAULT_CONFIG = 'DEFAULT'
_OUR_EXTENSION = 'webpack_loader.contrib.jinja2ext.WebpackExtension'


class LoaderTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.cleanup_bundles_folder()

    def cleanup_bundles_folder(self):
        rmtree('./assets/django_webpack_loader_bundles', ignore_errors=True)

    def compile_bundles(self, config, wait=None):
        if wait:
            time.sleep(wait)
        call(['./node_modules/.bin/webpack', '--config', config])

    def test_config_check(self):
        from webpack_loader.apps import webpack_cfg_check
        from webpack_loader.errors import BAD_CONFIG_ERROR

        with self.settings(WEBPACK_LOADER={
            'BUNDLE_DIR_NAME': 'django_webpack_loader_bundles/',
            'STATS_FILE': 'webpack-stats.json',
        }):
            errors = webpack_cfg_check(None)
            expected_errors = [BAD_CONFIG_ERROR]
            self.assertEqual(errors, expected_errors)

        with self.settings(WEBPACK_LOADER={
            'DEFAULT': {}
        }):
            errors = webpack_cfg_check(None)
            expected_errors = []
            self.assertEqual(errors, expected_errors)

    def test_simple_and_css_extract(self):
        self.compile_bundles('webpack.config.simple.js')
        assets = get_loader(DEFAULT_CONFIG).get_assets()
        self.assertEqual(assets['status'], 'done')
        self.assertIn('chunks', assets)

        chunks = assets['chunks']
        self.assertIn('main', chunks)
        self.assertEqual(len(chunks), 1)

        files = assets['assets']
        self.assertEqual(
            files['main.css']['path'],
            os.path.join(
                settings.BASE_DIR,
                'assets/django_webpack_loader_bundles/main.css'))
        self.assertEqual(
            files['main.js']['path'],
            os.path.join(
                settings.BASE_DIR,
                'assets/django_webpack_loader_bundles/main.js'))

    def test_default_ignore_config_ignores_map_files(self):
        self.compile_bundles('webpack.config.sourcemaps.js')
        chunks = get_loader('NO_IGNORE_APP').get_bundle('main')
        has_map_files_chunks = \
            any(['.map' in chunk['name'] for chunk in chunks])

        self.assertTrue(has_map_files_chunks)

        chunks = get_loader(DEFAULT_CONFIG).get_bundle('main')
        has_map_files_chunks = \
            any(['.map' in chunk['name'] for chunk in chunks])

        self.assertFalse(has_map_files_chunks)

    def test_js_gzip_extract(self):
        self.compile_bundles('webpack.config.gzipTest.js')
        assets = get_loader(DEFAULT_CONFIG).get_assets()
        self.assertEqual(assets['status'], 'done')
        self.assertIn('chunks', assets)

        chunks = assets['chunks']
        self.assertIn('main', chunks)
        self.assertEqual(len(chunks), 1)

        files = assets['assets']
        self.assertEqual(
            files['main.css']['path'],
            os.path.join(
                settings.BASE_DIR,
                'assets/django_webpack_loader_bundles/main.css'))
        self.assertEqual(
            files['main.js.gz']['path'],
            os.path.join(
                settings.BASE_DIR,
                'assets/django_webpack_loader_bundles/main.js.gz'))

    def test_static_url(self):
        self.compile_bundles('webpack.config.publicPath.js')
        assets = get_loader(DEFAULT_CONFIG).get_assets()
        self.assertEqual(assets['status'], 'done')
        self.assertEqual(assets['publicPath'],
                         'http://custom-static-host.com/')

    def test_code_spliting(self):
        self.compile_bundles('webpack.config.split.js')
        assets = get_loader(DEFAULT_CONFIG).get_assets()
        self.assertEqual(assets['status'], 'done')
        self.assertIn('chunks', assets)

        chunks = assets['chunks']
        self.assertIn('main', chunks)
        self.assertEquals(len(chunks), 1)

        files = assets['assets']
        self.assertEqual(files['main.js']['path'], os.path.join(
            settings.BASE_DIR, 'assets/django_webpack_loader_bundles/main.js'))
        self.assertEqual(files['vendors.js']['path'], os.path.join(
            settings.BASE_DIR,
            'assets/django_webpack_loader_bundles/vendors.js'))

    def test_templatetags(self):
        self.compile_bundles('webpack.config.simple.js')
        self.compile_bundles('webpack.config.app2.js')
        view = TemplateView.as_view(template_name='home.html')
        request = self.factory.get('/')
        result = view(request)
        self.assertIn((
            '<link href="/static/django_webpack_loader_bundles/main.css" '
            'rel="stylesheet" />'),
            result.rendered_content)
        self.assertIn((
            '<script src="/static/django_webpack_loader_bundles/main.js" '
            'async charset="UTF-8"></script>'), result.rendered_content)

        self.assertIn((
            '<link href="/static/django_webpack_loader_bundles/app2.css" '
            'rel="stylesheet" />'), result.rendered_content)
        self.assertIn((
            '<script src="/static/django_webpack_loader_bundles/app2.js" >'
            '</script>'), result.rendered_content)
        self.assertIn(
            '<img src="/static/my-image.png"/>', result.rendered_content)

        view = TemplateView.as_view(template_name='only_files.html')
        result = view(request)
        self.assertIn((
            "var contentCss = "
            "'/static/django_webpack_loader_bundles/main.css'"),
            result.rendered_content)
        self.assertIn(
            "var contentJS = '/static/django_webpack_loader_bundles/main.js'",
            result.rendered_content)

        self.compile_bundles('webpack.config.publicPath.js')
        view = TemplateView.as_view(template_name='home.html')
        request = self.factory.get('/')
        result = view(request)
        self.assertIn(
            '<img src="http://custom-static-host.com/my-image.png"/>',
            result.rendered_content)

    def test_preload(self):
        self.compile_bundles('webpack.config.simple.js')
        view = TemplateView.as_view(template_name='preload.html')
        request = self.factory.get('/')
        result = view(request)

        # Preload
        self.assertIn((
            '<link href="/static/django_webpack_loader_bundles/main.css" '
            'rel="preload" as="style" />'), result.rendered_content)
        self.assertIn((
            '<link rel="preload" as="script" href="/static/'
            'django_webpack_loader_bundles/main.js" />'),
            result.rendered_content)

        # Resources
        self.assertIn((
            '<link href="/static/django_webpack_loader_bundles/main.css" '
            'rel="stylesheet" />'), result.rendered_content)
        self.assertIn((
            '<script src="/static/django_webpack_loader_bundles/main.js" >'
            '</script>'), result.rendered_content)

    def test_append_extensions(self):
        self.compile_bundles('webpack.config.gzipTest.js')
        view = TemplateView.as_view(template_name='append_extensions.html')
        request = self.factory.get('/')
        result = view(request)

        self.assertIn((
            '<script src="/static/django_webpack_loader_bundles/main.js.gz" >'
            '</script>'), result.rendered_content)

    def test_jinja2(self):
        self.compile_bundles('webpack.config.simple.js')
        self.compile_bundles('webpack.config.app2.js')
        view = TemplateView.as_view(template_name='home.jinja')

        settings = {
            'TEMPLATES': [
                {
                    'BACKEND': 'django_jinja.backend.Jinja2',
                    'APP_DIRS': True,
                    'OPTIONS': {
                        'match_extension': '.jinja',
                        'extensions': DEFAULT_EXTENSIONS + [_OUR_EXTENSION],
                    }
                },
            ]
        }
        with self.settings(**settings):
            request = self.factory.get('/')
            result = view(request)
            self.assertIn((
                '<link href="/static/django_webpack_loader_bundles'
                '/main.css" rel="stylesheet" />'), result.rendered_content)
            self.assertIn((
                '<script src="/static/django_webpack_loader_bundles/main.js" '
                'async charset="UTF-8"></script>'), result.rendered_content)

    def test_reporting_errors(self):
        self.compile_bundles('webpack.config.error.js')
        try:
            get_loader(DEFAULT_CONFIG).get_bundle('main')
        except WebpackError as e:
            self.assertIn(
                "Can't resolve 'the-library-that-did-not-exist'", str(e))

    def test_missing_bundle(self):
        missing_bundle_name = 'missing_bundle'
        self.compile_bundles('webpack.config.simple.js')
        try:
            get_loader(DEFAULT_CONFIG).get_bundle(missing_bundle_name)
        except WebpackBundleLookupError as e:
            self.assertIn(
                'Cannot resolve bundle {0}'.format(missing_bundle_name),
                str(e))

    def test_missing_stats_file(self):
        stats_file = settings.WEBPACK_LOADER[DEFAULT_CONFIG]['STATS_FILE']
        if os.path.exists(stats_file):
            os.remove(stats_file)
        try:
            get_loader(DEFAULT_CONFIG).get_assets()
        except IOError as e:
            expected = (
                'Error reading {0}. Are you sure webpack has generated the '
                'file and the path is correct?'
            ).format(stats_file)
            self.assertIn(expected, str(e))

    def test_timeouts(self):
        with self.settings(DEBUG=True):
            statsfile = settings.WEBPACK_LOADER[DEFAULT_CONFIG]['STATS_FILE']
            with open(statsfile, 'w') as fd:
                fd.write(json.dumps({'status': 'compile'}))
            loader = get_loader(DEFAULT_CONFIG)
            loader.config['TIMEOUT'] = 0.1
            with self.assertRaises(WebpackLoaderTimeoutError):
                loader.get_bundle('main')

    def test_bad_status_in_production(self):
        statsfile = settings.WEBPACK_LOADER[DEFAULT_CONFIG]['STATS_FILE']
        with open(statsfile, 'w') as fd:
            fd.write(json.dumps({'status': 'unexpected-status'}))

        try:
            get_loader(DEFAULT_CONFIG).get_bundle('main')
        except WebpackLoaderBadStatsError as e:
            self.assertIn((
                "The stats file does not contain valid data. Make sure "
                "webpack-bundle-tracker plugin is enabled and try to run"
                " webpack again."
            ), str(e))

    def test_request_blocking(self):
        # FIXME: This will work 99% time but there is no guarantee with the
        # 4 second thing. Need a better way to detect if request was blocked on
        # not.
        wait_for = 4
        view = TemplateView.as_view(template_name='home.html')

        with self.settings(DEBUG=True):
            statsfile = settings.WEBPACK_LOADER[DEFAULT_CONFIG]['STATS_FILE']
            with open(statsfile, 'w') as fd:
                fd.write(json.dumps({'status': 'compile'}))
            then = time.time()
            request = self.factory.get('/')
            result = view(request)
            t = Thread(
                target=self.compile_bundles,
                args=('webpack.config.simple.js', wait_for))
            t2 = Thread(
                target=self.compile_bundles,
                args=('webpack.config.app2.js', wait_for))
            t.start()
            t2.start()
            result.rendered_content
            elapsed = time.time() - then
            t.join()
            t2.join()
            self.assertTrue(elapsed >= wait_for)

        with self.settings(DEBUG=False):
            self.compile_bundles('webpack.config.simple.js')
            self.compile_bundles('webpack.config.app2.js')
            then = time.time()
            request = self.factory.get('/')
            result = view(request)
            result.rendered_content
            elapsed = time.time() - then
            self.assertTrue(elapsed < wait_for)

    def test_skip_common_chunks_djangoengine(self):
        """Test case for deduplication of modules with the django engine."""
        self.compile_bundles('webpack.config.skipCommon.js')

        django_engine = engines['django']
        dups_template = django_engine.from_string(template_code=(
            r'{% load render_bundle from webpack_loader %}'
            r'{% render_bundle "app1" %}'
            r'{% render_bundle "app2" %}'))  # type: Template
        request = self.factory.get(path='/')
        asset_vendor = (
            '<script src="/static/django_webpack_loader_bundles/vendors.js" >'
            '</script>')
        asset_app1 = (
            '<script src="/static/django_webpack_loader_bundles/app1.js" >'
            '</script>')
        asset_app2 = (
            '<script src="/static/django_webpack_loader_bundles/app2.js" >'
            '</script>')
        rendered_template = dups_template.render(
            context=None, request=request)
        used_tags = getattr(request, '_webpack_loader_used_tags', None)

        self.assertIsNotNone(used_tags, msg=(
            '_webpack_loader_used_tags should be a property of request!'))
        self.assertEqual(rendered_template.count(asset_app1), 1)
        self.assertEqual(rendered_template.count(asset_app2), 1)
        self.assertEqual(rendered_template.count(asset_vendor), 2)

        nodups_template = django_engine.from_string(template_code=(
            r'{% load render_bundle from webpack_loader %}'
            r'{% render_bundle "app1" %}'
            r'{% render_bundle "app2" skip_common_chunks=True %}')
        )  # type: Template
        request = self.factory.get(path='/')
        rendered_template = nodups_template.render(
            context=None, request=request)
        used_tags = getattr(request, '_webpack_loader_used_tags', None)

        self.assertIsNotNone(used_tags, msg=(
            '_webpack_loader_used_tags should be a property of request!'))
        self.assertEqual(rendered_template.count(asset_app1), 1)
        self.assertEqual(rendered_template.count(asset_app2), 1)
        self.assertEqual(rendered_template.count(asset_vendor), 1)

    def test_skip_common_chunks_jinja2engine(self):
        """Test case for deduplication of modules with the Jinja2 engine."""
        self.compile_bundles('webpack.config.skipCommon.js')

        view = TemplateView.as_view(template_name='home-deduplicated.jinja')
        settings = {
            'TEMPLATES': [
                {
                    'BACKEND': 'django_jinja.backend.Jinja2',
                    'APP_DIRS': True,
                    'OPTIONS': {
                        'match_extension': '.jinja',
                        'extensions': DEFAULT_EXTENSIONS + [_OUR_EXTENSION],
                    }
                },
            ]
        }
        asset_vendor = (
            '<script src="/static/django_webpack_loader_bundles/vendors.js" >'
            '</script>')
        asset_app1 = (
            '<script src="/static/django_webpack_loader_bundles/app1.js" >'
            '</script>')
        asset_app2 = (
            '<script src="/static/django_webpack_loader_bundles/app2.js" >'
            '</script>')

        with self.settings(**settings):
            request = self.factory.get('/')
            result = view(request)  # type: TemplateResponse
            content = result.rendered_content
        self.assertIn(asset_vendor, content)
        self.assertIn(asset_app1, content)
        self.assertIn(asset_app2, content)
        self.assertEqual(content.count(asset_vendor), 1)
        self.assertEqual(content.count(asset_app1), 1)
        self.assertEqual(content.count(asset_app2), 1)
        used_tags = getattr(request, '_webpack_loader_used_tags', None)
        self.assertIsNotNone(used_tags, msg=(
            '_webpack_loader_used_tags should be a property of request!'))
