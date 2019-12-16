# =============================================================================
# Ural URL Normalization Function
# =============================================================================
#
# A handy function relying on heuristics to find and drop irrelevant or
# non-discriminant parts of a URL.
#
import re
import pycountry
from os.path import normpath, splitext

from ural.ensure_protocol import ensure_protocol
from ural.utils import (
    parse_qsl,
    quote,
    urlsplit,
    urlunsplit,
    unquote,
    SplitResult
)
from ural.patterns import PROTOCOL_RE, QUERY_VALUE_IN_URL_TEMPLATE

RESERVED_CHARACTERS = ';,/?:@&=+$'
UNRESERVED_CHARACTERS = '-_.!~*\'()'
SAFE_CHARACTERS = RESERVED_CHARACTERS + UNRESERVED_CHARACTERS

MISTAKES_RE = re.compile(r'&amp;')

OBVIOUS_REDIRECTS_RE = re.compile(QUERY_VALUE_IN_URL_TEMPLATE % r'(?:redirect(?:_to)?|url|[lu])', re.I)

IRRELEVANT_QUERY_PATTERN = r'^(?:__twitter_impression|echobox|fbclid|feature|recruiter|fref|igshid|ncid|utm_.+%s|s?een|xt(?:loc|ref|cr|np|or|s))$'
IRRELEVANT_SUBDOMAIN_PATTERN = r'\b(?:www\d?|mobile%s|m)\.'

AMP_QUERY_PATTERN = r'|amp_.+|amp'
AMP_SUBDOMAIN_PATTERN = r'|amp'
AMP_SUFFIXES_RE = re.compile(r'(?:\.amp(?=\.html$)|\.amp/?$|(?<=/)amp/?$)', re.I)
AMPPROJECT_REDIRECTION_RE = re.compile(r'^/[cv]/(?:s/)?', re.I)

IRRELEVANT_QUERY_RE = re.compile(IRRELEVANT_QUERY_PATTERN % r'', re.I)
IRRELEVANT_SUBDOMAIN_RE = re.compile(IRRELEVANT_SUBDOMAIN_PATTERN % r'', re.I)

IRRELEVANT_QUERY_AMP_RE = re.compile(IRRELEVANT_QUERY_PATTERN % AMP_QUERY_PATTERN, re.I)
IRRELEVANT_SUBDOMAIN_AMP_RE = re.compile(IRRELEVANT_SUBDOMAIN_PATTERN % AMP_SUBDOMAIN_PATTERN, re.I)

IRRELEVANT_QUERY_COMBOS = {
    'platform': ('hootsuite', ),
    'ref': set([
        'bookmark',
        'bookmarks',
        'distributor_share',
        'fb',
        'fb_i',
        'm_notif',
        'nf',
        'notif',
        'shortener',
        'ts',
        'tw',
        'tw_i',
        'twhr',
        'twhs',
        'twitter',
        'viral'
    ]),
    'sns': ('tw', ),
    'spref': ('fb', 'ts', 'tw', 'tw_i', 'twitter')
}


def attempt_to_decode_idna(string):
    try:
        return string.encode('utf8').decode('idna')
    except:
        return string


def stringify_qs(item):
    if item[1] == '':
        return item[0]

    return '%s=%s' % item


def should_strip_query_item(item, normalize_amp=True):
    key = item[0].lower()

    pattern = IRRELEVANT_QUERY_AMP_RE if normalize_amp else IRRELEVANT_QUERY_RE

    if pattern.match(key):
        return True

    value = item[1]

    if key in IRRELEVANT_QUERY_COMBOS:
        return value in IRRELEVANT_QUERY_COMBOS[key]

    return False


def should_strip_fragment(fragment):
    if fragment == '!/' or fragment == '/' or fragment == '!':
        return False

    return (
        fragment.startswith('/') or
        fragment.startswith('!')
    )


def decode_punycode(netloc):
    if 'xn--' in netloc:
        netloc = '.'.join(
            attempt_to_decode_idna(x) for x in netloc.split('.')
        )

    return netloc


def strip_lang_subdomains_from_netloc(netloc):
    if netloc.count('.') > 1:
        subdomain, remaining_netloc = netloc.split('.', 1)
        if len(subdomain) == 5 and '-' in subdomain:
            lang, country = subdomain.split('-', 1)
            if len(lang) == 2 and len(country) == 2:
                if pycountry.countries.get(alpha_2=lang.upper()) and pycountry.countries.get(alpha_2=country.upper()):
                    netloc = remaining_netloc
        elif len(subdomain) == 2:
            if pycountry.countries.get(alpha_2=subdomain.upper()):
                netloc = remaining_netloc

    return netloc


def resolve_ampproject_redirect(splitted):
    if (
        splitted.hostname and
        splitted.hostname.endswith('.ampproject.org') and
        AMPPROJECT_REDIRECTION_RE.search(splitted.path)
    ):
        amp_redirected = 'https://' + AMPPROJECT_REDIRECTION_RE.sub('', splitted.path)

        if splitted.query:
            amp_redirected += '?' + splitted.query

        if splitted.fragment:
            amp_redirected += '#' + splitted.fragment

        splitted = urlsplit(amp_redirected)

    return splitted


def normalize_url(url, unsplit=True, sort_query=True, strip_authentication=True,
                  strip_trailing_slash=False, strip_index=True, strip_protocol=True,
                  strip_irrelevant_subdomain=True, strip_lang_subdomains=False,
                  strip_fragment='except-routing', normalize_amp=True, fix_common_mistakes=True,
                  resolve_obvious_redirects=False, quoted=True):
    """
    Function normalizing the given url by stripping it of usually
    non-discriminant parts such as irrelevant query items or sub-domains etc.

    This is a very useful utility when attempting to match similar urls
    written slightly differently when shared on social media etc.

    Args:
        url (str): Target URL as a string.
        sort_query (bool, optional): Whether to sort query items or not.
            Defaults to `True`.
        strip_authentication (bool, optional): Whether to drop authentication.
            Defaults to `True`.
        strip_trailing_slash (bool, optional): Whether to drop trailing slash.
            Defaults to `False`.
        strip_index (bool, optional): Whether to drop trailing index at the end
            of the url. Defaults to `True`.
        strip_lang_subdomains (bool, optional): Whether to drop language subdomains
            (ex: 'fr-FR.lemonde.fr' to only 'lemonde.fr' because 'fr-FR' isn't a relevant subdomain, it indicates the language and the country).
            Defaults to `False`.
        strip_fragment (bool|str, optional): Whether to drop non-routing fragment from the url?
            If set to `except-routing` will only drop non-routing fragment (i.e. fragments that
            do not contain a "/").
            Defaults to `except-routing`.
        normalize_amp (bool, optional): Whether to attempt to normalize Google
            AMP urls. Defaults to True.
        fix_common_mistakes (bool, optional): Whether to attempt solving common mistakes.
            Defaults to True.
        resolve_obvious_redirects (bool, optional): Whether to attempt resolving common
            redirects by leveraging well-known GET parameters. Defaults to `False`.
        quoted (bool, optional): Normalizing to quoted or unquoted.
            Defaults to True.

    Returns:
        string: The normalized url.

    """
    original_url_arg = url

    if resolve_obvious_redirects:
        obvious_redirect_match = re.search(OBVIOUS_REDIRECTS_RE, url)

        if obvious_redirect_match is not None:
            target = unquote(obvious_redirect_match.group(1))

            if target.startswith('http://') or target.startswith('https://'):
                url = target

    if isinstance(url, SplitResult):
        has_protocol = bool(splitted.scheme)
        splitted = url
    else:
        has_protocol = PROTOCOL_RE.match(url)

        # Ensuring scheme so parsing works correctly
        if not has_protocol:
            url = 'http://' + url

        # Parsing
        try:
            splitted = urlsplit(url)
        except ValueError:
            return original_url_arg

    # Handling *.ampproject.org redirections
    if normalize_amp:
        splitted = resolve_ampproject_redirect(splitted)

    scheme, netloc, path, query, fragment = splitted

    # Fixing common mistakes
    if fix_common_mistakes:
        if query:
            query = re.sub(MISTAKES_RE, '&', query)

    # Handling punycode
    netloc = decode_punycode(netloc)

    # Dropping :80 & :443
    if netloc.endswith(':80'):
        netloc = netloc[:-3]
    elif netloc.endswith(':443'):
        netloc = netloc[:-4]

    # Normalizing the path
    if path:
        trailing_slash = False
        if path.endswith('/') and len(path) > 1:
            trailing_slash = True
        path = normpath(path)
        if trailing_slash and not strip_trailing_slash:
            path = path + '/'

    # Handling Google AMP suffixes
    if normalize_amp:
        path = AMP_SUFFIXES_RE.sub('', path)

    # Dropping index:
    if strip_index:
        segments = path.rsplit('/', 1)

        if len(segments) != 0:
            last_segment = segments[-1]
            filename, ext = splitext(last_segment)

            if filename == 'index':
                segments.pop()
                path = '/'.join(segments)

    # Dropping irrelevant query items
    if query:
        qsl = parse_qsl(query, keep_blank_values=True)
        qsl = [
            stringify_qs(item)
            for item in qsl
            if not should_strip_query_item(item, normalize_amp=normalize_amp)
        ]

        if sort_query:
            qsl = sorted(qsl)

        query = '&'.join(qsl)

    # Dropping fragment if it's not routing
    if fragment and strip_fragment:
        if strip_fragment is True or not should_strip_fragment(fragment):
            fragment = ''

    # Always dropping trailing slash with empty query & fragment
    if path == '/' and not fragment and not query:
        path = ''

    # Dropping irrelevant subdomains
    if strip_irrelevant_subdomain:
        netloc = re.sub(
            IRRELEVANT_SUBDOMAIN_AMP_RE if normalize_amp else IRRELEVANT_SUBDOMAIN_RE,
            '',
            netloc
        )

    # Dropping language as subdomains
    if strip_lang_subdomains:
        netloc = strip_lang_subdomains_from_netloc(netloc)

    # Dropping scheme
    if strip_protocol or not has_protocol:
        scheme = ''

    # Dropping authentication
    if strip_authentication:
        netloc = netloc.split('@', 1)[-1]

    # Normalizing AMP subdomains
    if normalize_amp and netloc.startswith('amp-'):
        netloc = netloc[4:]

    # Dropping trailing slash
    if strip_trailing_slash and path.endswith('/'):
        path = path.rstrip('/')

    # Quoting or not
    if quoted:
        path = quote(path)
        query = quote(query, RESERVED_CHARACTERS)
        fragment = quote(fragment, SAFE_CHARACTERS)
    else:
        path = unquote(path)
        query = unquote(query)
        fragment = unquote(fragment)

    # Result
    result = SplitResult(
        scheme,
        netloc.lower(),
        path,
        query,
        fragment
    )

    if not unsplit:
        return result

    # TODO: check if works with `unsplit=False`
    if strip_protocol or not has_protocol:
        result = urlunsplit(result)[2:]
    else:
        result = urlunsplit(result)

    return result


def get_normalized_hostname(url, normalize_amp=True, strip_lang_subdomains=False):
    if isinstance(url, SplitResult):
        splitted = url
    else:
        try:
            splitted = urlsplit(ensure_protocol(url))
        except ValueError:
            return None

    if normalize_amp:
        splitted = resolve_ampproject_redirect(splitted)

    if not splitted.hostname:
        return None

    hostname = splitted.hostname.lower()

    pattern = IRRELEVANT_SUBDOMAIN_AMP_RE if normalize_amp else IRRELEVANT_SUBDOMAIN_RE

    hostname = pattern.sub('', hostname)

    if normalize_amp and hostname.startswith('amp-'):
        hostname = hostname[4:]

    hostname = decode_punycode(hostname)

    if strip_lang_subdomains:
        hostname = strip_lang_subdomains_from_netloc(hostname)

    return hostname
