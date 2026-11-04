"""A built named-custom agent reports its menu identity, not the shared billing class.

Upstream's durable identity is the ``custom:<key>`` slug (``custom:cpa``). Desktop
matches that slug and its aliases. ``agent.provider`` is the billing class
``custom`` for every named endpoint, so session.info must recover the slug or
the row stays unchecked and the composer tooltip reads ``custom``.
"""
from types import SimpleNamespace

from gateway.session_local_inventory import _session_provider, agent_inventory, session_inventory


def _home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'config.yaml').write_text(
        'model:\n'
        '  default: grok-4.6\n'
        '  provider: cpa\n'
        'providers:\n'
        '  cpa:\n'
        '    name: CPA\n'
        '    base_url: http://cpa.example/v1\n'
        '    model: grok-4.6\n'
        '  other:\n'
        '    name: Other\n'
        '    base_url: http://other.example/v1\n'
        '    model: other-model\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('HERMES_HOME', str(home))
    return home


def _agent(**fields):
    base = {'tools': None, '_cached_system_prompt': '', 'enabled_toolsets': []}
    base.update(fields)
    return SimpleNamespace(**base)


def test_named_custom_endpoint_reports_its_config_key(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    agent = _agent(provider='custom', base_url='http://cpa.example/v1', model='grok-4.6')
    assert _session_provider(agent) == 'custom:cpa'
    assert agent_inventory(agent)['provider'] == 'custom:cpa'


def test_specific_provider_is_not_rewritten(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    assert _session_provider(_agent(provider='anthropic', base_url='http://cpa.example/v1', model='grok-4.6')) == 'anthropic'
    assert _session_provider(_agent(provider='custom:cpa', base_url='http://cpa.example/v1', model='grok-4.6')) == 'custom:cpa'


def test_unnamed_custom_endpoint_stays_the_billing_class(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    agent = _agent(provider='custom', base_url='http://unknown.example/v1', model='not-listed')
    assert _session_provider(agent) == 'custom'


def test_session_inventory_reports_the_config_key(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    authority = SimpleNamespace(
        runner=SimpleNamespace(config=SimpleNamespace(multiplex_profiles=False)),
        profile_id='fixture',
    )
    agent = _agent(provider='custom', base_url='http://cpa.example/v1', model='grok-4.6')
    assert session_inventory(authority, None, agent, str(tmp_path))['provider'] == 'custom:cpa'
