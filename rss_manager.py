import json
import os
import re
import requests
import threading
from urllib.parse import urlparse
from defusedxml import ElementTree as ET
from app_paths import get_data_dir

RSS_FILE = os.path.join(get_data_dir(), "rss.json")

class RSSManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.feeds = {} # url -> {'alias': str, 'last_update': float, 'articles': []}
        self.rules = [] # list of {'pattern': str, 'enabled': bool}
        self.load()

    def load(self):
        with self.lock:
            if os.path.exists(RSS_FILE):
                try:
                    with open(RSS_FILE, 'r') as f:
                        data = json.load(f)
                        self.feeds = data.get('feeds', {})
                        self.rules = data.get('rules', [])
                except Exception:
                    return

    def save(self):
        with self.lock:
            data = {'feeds': self.feeds, 'rules': self.rules}
            try:
                # Atomic write: a direct open('w') truncates rss.json immediately,
                # so a crash mid-write loses all feeds/rules. Write a temp + rename.
                tmp = f"{RSS_FILE}.{os.getpid()}.tmp"
                try:
                    with open(tmp, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, RSS_FILE)
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
            except Exception as e:
                print(f"Failed to save RSS: {e}")

    def add_feed(self, url, alias=""):
        with self.lock:
            if url not in self.feeds:
                self.feeds[url] = {'alias': alias, 'last_update': 0, 'articles': []}
                self.save()
                return True
            return False

    def remove_feed(self, url):
        with self.lock:
            if url in self.feeds:
                del self.feeds[url]
                self.save()

    def add_rule(self, pattern, rule_type="accept", scope=None):
        """
        Add a rule.
        scope: None for global, or a list of feed URLs this rule applies to.
        """
        with self.lock:
            self.rules.append({'pattern': pattern, 'enabled': True, 'type': rule_type, 'scope': scope})
            self.save()

    def remove_rule(self, index):
        with self.lock:
            if 0 <= index < len(self.rules):
                del self.rules[index]
                self.save()

    def update_rule(self, index, data):
        with self.lock:
            if 0 <= index < len(self.rules):
                self.rules[index].update(data)
                self.save()

    def reset_all(self):
        with self.lock:
            self.feeds = {}
            self.rules = []
            self.save()

    def is_downloaded(self, url, uid):
        """True if `uid` from feed `url` has already been auto-downloaded."""
        if not uid:
            return False
        with self.lock:
            feed = self.feeds.get(url)
            if not feed:
                return False
            return uid in feed.get('downloaded', [])

    def mark_downloaded(self, url, uid):
        """Record `uid` as auto-downloaded so it is not re-added on the next poll."""
        if not uid:
            return
        with self.lock:
            feed = self.feeds.get(url)
            if feed is None:
                return
            seen = feed.setdefault('downloaded', [])
            if uid in seen:
                return
            seen.append(uid)
            # Bound growth: stale items drop out of the feed and never recur.
            if len(seen) > 1000:
                del seen[:-1000]
            self.save()

    def fetch_feed(self, url):
        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() not in ('http', 'https'):
                raise ValueError("RSS feed URL must use http or https")
            # Cap the response size to avoid memory exhaustion from a hostile/huge feed.
            r = requests.get(url, timeout=10, stream=True)
            r.raise_for_status()
            content = b""
            for chunk in r.iter_content(8192):
                content += chunk
                if len(content) > 10 * 1024 * 1024:  # 10 MB
                    raise ValueError("RSS feed exceeds 10 MB limit")

            # Simple RSS/Atom parser (defusedxml blocks XXE / entity expansion)
            root = ET.fromstring(content)
            articles = []
            
            # Handle RSS 2.0
            for item in root.findall('./channel/item'):
                title = item.find('title')
                link = item.find('link') # usually web link
                enclosure = item.find('enclosure') # usually torrent url
                
                # Torrent link might be in link or enclosure
                t_url = ""
                if enclosure is not None and enclosure.get('type') == 'application/x-bittorrent':
                    t_url = enclosure.get('url')
                elif link is not None:
                    t_url = link.text
                
                if title is not None and t_url:
                    articles.append({
                        'title': title.text or "",  # avoid None -> re.search TypeError
                        'link': t_url,
                        'uid': t_url # simplified UID
                    })
            
            with self.lock:
                if url in self.feeds:
                    self.feeds[url]['articles'] = articles
                    import time
                    self.feeds[url]['last_update'] = time.time()
                    self.feeds[url]['last_error'] = None # Clear error
            
            return articles
        except Exception as e:
            err_msg = str(e)
            print(f"RSS Fetch Error {url}: {err_msg}")
            with self.lock:
                if url in self.feeds:
                    self.feeds[url]['last_error'] = err_msg
            return []

    def get_matches(self, articles, feed_url=None):
        matches = []
        # Rules and feeds might change, so capture a snapshot or lock?
        # get_matches is read-only usually, but accessing self.rules needs safety if modified elsewhere
        with self.lock:
            current_rules = list(self.rules) # Copy

        for a in articles:
            # Filter rules applicable to this feed
            applicable_rules = []
            for r in current_rules:
                if not r.get('enabled', True):
                    continue
                scope = r.get('scope')
                # If scope is None, it's global. If feed_url matches scope, it applies.
                if scope is None or (feed_url and feed_url in scope):
                    applicable_rules.append(r)

            # 1. Reject Check
            rejected = False
            for rule in applicable_rules:
                if rule.get('type') == 'reject':
                    try:
                        if re.search(rule['pattern'], a['title'], re.IGNORECASE):
                            rejected = True
                            break
                    except re.error:
                        continue
            if rejected:
                continue

            # 2. Accept Check
            for rule in applicable_rules:
                if rule.get('type', 'accept') == 'accept':
                    try:
                        if re.search(rule['pattern'], a['title'], re.IGNORECASE):
                            matches.append(a)
                            break
                    except re.error:
                        continue
        return matches

    def import_flexget_config(self, path):
        try:
            import yaml
        except ImportError:
            raise Exception("PyYAML is required to import FlexGet configs.")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except Exception as e:
            raise Exception(f"Failed to parse YAML: {e}")

        if not config or 'tasks' not in config:
            return 0, 0

        from config_manager import ConfigManager
        cm = ConfigManager()
        existing_profiles = cm.get_profiles()
        
        tasks = config.get('tasks', {})
        count_feeds = 0
        count_rules = 0
        
        # Helper to avoid dupes
        def profile_exists(url, user):
            for pid, p in existing_profiles.items():
                if p.get('url') == url and p.get('user') == user:
                    return True
            return False

        with self.lock:
            for task_name, task_config in tasks.items():
                if not isinstance(task_config, dict):
                    continue

                # 0. Profile (qBittorrent)
                qbit = task_config.get('qbittorrent')
                if qbit and isinstance(qbit, dict):
                    host = qbit.get('host', 'localhost')
                    port = qbit.get('port', 8080)
                    user = qbit.get('username', '')
                    pw = qbit.get('password', '')
                    
                    url = f"http://{host}:{port}"
                    if not profile_exists(url, user):
                        cm.add_profile(f"{task_name} qBit", "qbittorrent", url, user, pw)

                # 1. RSS Feeds (Collect task URLs for scoping)
                task_feed_urls = []
                
                rss_entry = task_config.get('rss')
                if rss_entry:
                    url = ""
                    if isinstance(rss_entry, str):
                        url = rss_entry
                    elif isinstance(rss_entry, dict):
                        url = rss_entry.get('url')
                    
                    if url:
                        task_feed_urls.append(url)
                        # Avoid nested lock if add_feed uses it.
                        # Since we are holding lock, we should manually manipulate dict or make add_feed reentrant (RLock handles this).
                        if url not in self.feeds:
                            self.feeds[url] = {'alias': f"{task_name} RSS", 'last_update': 0, 'articles': []}
                            count_feeds += 1
                
                inputs = task_config.get('inputs', [])
                if isinstance(inputs, list):
                    for inp in inputs:
                        if isinstance(inp, dict) and 'rss' in inp:
                            val = inp['rss']
                            url = ""
                            if isinstance(val, str):
                                url = val
                            elif isinstance(val, dict):
                                url = val.get('url')
                            
                            if url:
                                task_feed_urls.append(url)
                                if url not in self.feeds:
                                    self.feeds[url] = {'alias': f"{task_name} RSS", 'last_update': 0, 'articles': []}
                                    count_feeds += 1

                # 2. Rules (Regex) - Scope them to task_feed_urls
                regexp = task_config.get('regexp', {})
                if isinstance(regexp, dict):
                    # Accept
                    accept = regexp.get('accept', [])
                    if isinstance(accept, list):
                        for pattern in accept:
                            self.rules.append({'pattern': str(pattern), 'enabled': True, 'type': 'accept', 'scope': task_feed_urls})
                            count_rules += 1
                    # Reject
                    reject = regexp.get('reject', [])
                    if isinstance(reject, list):
                        for pattern in reject:
                            self.rules.append({'pattern': str(pattern), 'enabled': True, 'type': 'reject', 'scope': task_feed_urls})
                            count_rules += 1
                
                # 3. Series - Scope them to task_feed_urls
                series = task_config.get('series', [])
                if isinstance(series, list):
                    for s in series:
                        name = ""
                        if isinstance(s, str):
                            name = s
                        elif isinstance(s, dict):
                            name = list(s.keys())[0] if s else ""
                        
                        if name:
                            pattern = re.escape(name).replace(r"\ ", ".*")
                            self.rules.append({'pattern': pattern, 'enabled': True, 'type': 'accept', 'scope': task_feed_urls})
                            count_rules += 1
                            
                # 4. Accept All - Scope them to task_feed_urls
                if task_config.get('accept_all'):
                     self.rules.append({'pattern': ".*", 'enabled': True, 'type': 'accept', 'scope': task_feed_urls})
                     count_rules += 1
            
            self.save()
        
        return count_feeds, count_rules
