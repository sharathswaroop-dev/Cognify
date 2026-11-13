import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'ask.dart';
import 'jobs.dart';
import 'learn.dart';
import 'roles.dart';
import 'theme.dart';

/// The technician's app: jobs, the chat, the learning replay, and, above all, job offers that arrive like ride requests.
class TechShell extends StatefulWidget {
  const TechShell({super.key});

  @override
  State<TechShell> createState() => _TechShellState();
}

class _TechShellState extends State<TechShell> {
  int _tab = 0;
  Map<String, dynamic>? _status;
  Map<String, dynamic>? _active;
  Timer? _timer;
  bool _showing = false;
  bool _online = true;
  String _mode = 'manual';
  final Set<String> _handled = {};
  final Set<String> _switched = {};

  String get _tid => s(Api.user?['tech_id']);

  @override
  void initState() {
    super.initState();
    _loadStatus();
    _inbox();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _inbox());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadStatus() async {
    try {
      final st = await Api.get('/api/status');
      if (mounted) setState(() => _status = Map<String, dynamic>.from(st as Map));
    } catch (_) {}
  }

  Future<void> _inbox() async {
    if (_tid.isEmpty) return;
    try {
      final r = m(await Api.get('/api/tech/$_tid/inbox'));
      if (!mounted) return;
      setState(() {
        _active = r['active'] == null ? null : m(r['active']);
        _online = s(m(r['technician'])['duty']) != 'off';
        _mode = s(m(r['technician'])['mode']) == 'demo' ? 'demo' : 'manual';
        // once the OTP starts the work, the app becomes the assistant for that unit
        if (_active != null && s(_active!['status']) == 'working' && _switched.add(s(_active!['id']))) _tab = 1;
      });
      final offer = r['offer'] == null ? null : m(r['offer']);
      if (offer != null && !_showing && !_handled.contains(s(offer['id']))) {
        _showing = true;
        _handled.add(s(offer['id']));
        final res = await Navigator.of(context).push<Map<String, dynamic>>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => OfferScreen(offer: offer)));
        _showing = false;
        if (res != null && res['accepted'] == true && mounted) await _openJob(s(res['job_id']));
        if (res != null && res['lost'] == true && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Another technician was the better match for that job.')));
        }
      }
    } catch (_) {}
  }

  Future<void> _setMode(String mode) async {
    try {
      await Api.post('/api/tech/$_tid/mode', {'mode': mode});
      if (mounted) setState(() => _mode = mode);
    } on ApiError catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _setDuty(bool on) async {
    try {
      await Api.post('/api/tech/$_tid/duty', {'on': on});
      if (mounted) setState(() => _online = on);
    } on ApiError catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _openJob(String jobId) async {
    try {
      final jobs = l(await Api.get('/api/jobs/open?technician=${Uri.encodeComponent(_tid)}')).map(m).toList();
      final hit = jobs.where((j) => s(j['job_id']) == jobId).toList();
      if (hit.isNotEmpty && mounted) await Navigator.of(context).push(MaterialPageRoute(builder: (_) => JobScreen(job: hit.first)));
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final st = _status;
    final degraded = st?['memory_degraded'] == true;
    final band = (st?['band']?.toString() ?? '').startsWith('configured');
    final working = _active != null && const ['on_site', 'working'].contains(s(_active!['status']));
    final pages = <Widget>[
      const JobsScreen(),
      AskScreen(machineId: working ? s(m(_active!['machine'])['id']) : null, jobLabel: working ? s(_active!['site']) : null),
      const LearnScreen(),
    ];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text('Cognify', style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: -0.5)),
        actions: [
          if (st != null) ...[
            Pill(degraded ? 'local memory' : 'Hindsight', color: degraded ? C.amber : C.ok),
            const SizedBox(width: 6),
            Pill(band ? 'Band' : 'in-process', color: band ? C.ok : C.amber),
          ],
          IconButton(onPressed: () => signOut(context), icon: const Icon(Icons.logout_rounded, color: C.mute), tooltip: 'Sign out'),
        ],
      ),
      body: Column(children: [
        _DutyBar(online: _online, onJob: _active != null, onChanged: _setDuty),
        _ModeBar(mode: _mode, onChanged: _setMode),
        if (_active != null) _ActiveBanner(active: _active!, onOpen: () => _openJob(s(_active!['job_id']))),
        Expanded(child: IndexedStack(index: _tab, children: pages)),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.assignment_outlined), selectedIcon: Icon(Icons.assignment_rounded), label: 'Jobs'),
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline_rounded), selectedIcon: Icon(Icons.chat_bubble_rounded), label: 'Assistant'),
          NavigationDestination(icon: Icon(Icons.show_chart_rounded), selectedIcon: Icon(Icons.show_chart_rounded), label: 'Learn'),
        ],
      ),
    );
  }
}

/// Online / offline, like a ride-hailing captain: offline means no job offers at all.
class _DutyBar extends StatelessWidget {
  final bool online, onJob;
  final ValueChanged<bool> onChanged;
  const _DutyBar({required this.online, required this.onJob, required this.onChanged});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Panel(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          color: online ? const Color(0xFF0A2A1F) : C.s1,
          border: online ? const Color(0xFF136B4B) : C.line,
          child: Row(children: [
            Container(width: 10, height: 10, decoration: BoxDecoration(shape: BoxShape.circle, color: online ? C.ok : C.dim)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(online ? 'You are online' : 'You are offline', style: const TextStyle(fontWeight: FontWeight.w800)),
                Text(online ? 'Job offers near you will pop up here.' : 'You will not receive any job offers.', style: const TextStyle(color: C.mute, fontSize: 12.5)),
              ]),
            ),
            Switch(value: online, onChanged: onJob ? null : onChanged, activeThumbColor: C.ok),
          ]),
        ),
      );
}

/// Demo: the simulation plays this technician (accepts, drives, enters the OTP). Manual: the person with the phone decides.
class _ModeBar extends StatelessWidget {
  final String mode;
  final ValueChanged<String> onChanged;
  const _ModeBar({required this.mode, required this.onChanged});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Panel(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Text('MODE', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
              const Spacer(),
              SegmentedButton<String>(
                showSelectedIcon: false,
                style: const ButtonStyle(visualDensity: VisualDensity.compact),
                segments: const [
                  ButtonSegment(value: 'demo', label: Text('Demo')),
                  ButtonSegment(value: 'manual', label: Text('Manual')),
                ],
                selected: {mode},
                onSelectionChanged: (v) => onChanged(v.first),
              ),
            ]),
            const SizedBox(height: 6),
            Text(
              mode == 'demo'
                  ? 'Demo: the app plays you. Offers are accepted, the drive and the OTP happen by themselves.'
                  : 'Manual: you decide. Accept or reject offers, tap when you arrive, and enter the customer\'s OTP.',
              style: const TextStyle(color: C.mute, fontSize: 12.5, height: 1.4),
            ),
          ]),
        ),
      );
}

class _ActiveBanner extends StatelessWidget {
  final Map<String, dynamic> active;
  final VoidCallback onOpen;
  const _ActiveBanner({required this.active, required this.onOpen});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Panel(
          onTap: onOpen,
          color: C.deep,
          border: C.violet,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(children: [
            const Icon(Icons.directions_car_filled_rounded, color: C.cyan),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                  {'en_route': 'On your way', 'on_site': 'You are on site: ask the customer for the OTP', 'working': 'Work in progress'}[s(active['status'])] ?? 'Active job',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                Text('${s(active['site'])} · ${s(active['id'])}', style: const TextStyle(color: C.mute, fontSize: 12.5)),
              ]),
            ),
            const Icon(Icons.chevron_right_rounded, color: C.violet2),
          ]),
        ),
      );
}

// ============================================================ an offer arrives, like a ride request
class OfferScreen extends StatefulWidget {
  final Map<String, dynamic> offer;
  const OfferScreen({super.key, required this.offer});

  @override
  State<OfferScreen> createState() => _OfferScreenState();
}

class _OfferScreenState extends State<OfferScreen> {
  late int _left;
  Timer? _timer;
  bool _busy = false;
  bool _waiting = false;
  Timer? _poll;
  String? _error;

  @override
  void initState() {
    super.initState();
    _left = (widget.offer['expires_in'] as num?)?.toInt() ?? 45;
    _startWatch();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _left--);
      if (_left <= 0 && !_waiting) {
        _timer?.cancel();
        Navigator.of(context).pop(<String, dynamic>{'accepted': false});
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _poll?.cancel();
    super.dispose();
  }

  /// Everyone in the layer was notified at once. After accepting, wait a moment: the best match among those who accepted gets the job.
  void _waitForDecision() {
    setState(() {
      _waiting = true;
      _busy = false;
    });
  }

  /// Watches the request while this screen is open: closes it when the layer is decided (for you or for someone else) or the offer lapses.
  void _startWatch() {
    _poll = Timer.periodic(const Duration(milliseconds: 1200), (_) async {
      try {
        final r = m(await Api.get('/api/reports/${s(widget.offer['id'])}'));
        final a = r['assigned'] == null ? null : m(r['assigned']);
        if (!mounted) return;
        final me = s(Api.user?['tech_id']);
        if (a != null) {
          _poll?.cancel();
          if (s(a['id']) == me) {
            Navigator.of(context).pop(<String, dynamic>{'accepted': true, 'job_id': s(r['job_id'])});
          } else {
            Navigator.of(context).pop(<String, dynamic>{'accepted': false, 'lost': true});
          }
          return;
        }
        if (s(r['status']) != 'offered') {
          _poll?.cancel();
          Navigator.of(context).pop(<String, dynamic>{'accepted': false});
          return;
        }
        final mine = l(r['offers']).map(m).where((o) => s(o['tech_id']) == me).toList();
        if (mine.isNotEmpty) {
          final res = s(mine.last['result']);
          if (res == 'lost' || res == 'timeout') {
            _poll?.cancel();
            Navigator.of(context).pop(<String, dynamic>{'accepted': false, 'lost': res == 'lost'});
          }
        }
      } catch (_) {}
    });
  }

  Future<void> _answer(String action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = m(await Api.post('/api/reports/${s(widget.offer['id'])}/respond', {'tech_id': s(Api.user?['tech_id']), 'action': action}));
      if (!mounted) return;
      if (action == 'accept') {
        if (r['assigned'] != null && s(m(r['assigned'])['id']) == s(Api.user?['tech_id'])) {
          Navigator.of(context).pop(<String, dynamic>{'accepted': true, 'job_id': s(r['job_id'])});
        } else {
          _waitForDecision();
        }
        return;
      }
      Navigator.of(context).pop(<String, dynamic>{'accepted': false, 'job_id': s(r['job_id'])});
    } on ApiError catch (e) {
      if (!mounted) return;
      if (e.message.contains('no longer open')) {
        _poll?.cancel();
        Navigator.of(context).pop(<String, dynamic>{'accepted': false, 'lost': true});
        return;
      }
      setState(() {
        _busy = false;
        _error = e.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final o = widget.offer;
    final mach = o['machine'] == null ? <String, dynamic>{} : m(o['machine']);
    final sev = s(o['severity']);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Pill('NEW JOB OFFER', color: C.amber),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                decoration: BoxDecoration(color: C.s2, borderRadius: BorderRadius.circular(99), border: Border.all(color: _left <= 10 ? C.red : C.line2)),
                child: Text('${_left}s', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16, color: _left <= 10 ? C.red : C.text)),
              ),
            ]),
            const SizedBox(height: 16),
            ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: (_left / 45).clamp(0.0, 1.0), minHeight: 6, color: C.amber, backgroundColor: C.s3)),
            const SizedBox(height: 22),
            Text(s(o['symptom']), style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, height: 1.25, letterSpacing: -0.6)),
            const SizedBox(height: 12),
            Text('${s(o['site'])} · ${s(o['area'])}', style: const TextStyle(color: C.mute, fontSize: 15)),
            if (mach.isNotEmpty) Text('${s(mach['id'])} · ${s(mach['model'])} · ${s(mach['location'])}', style: const TextStyle(color: C.mute, fontSize: 14)),
            const SizedBox(height: 14),
            Row(children: [
              Pill(sev, color: sev == 'urgent' ? C.red : (sev == 'high' ? C.amber : C.cyan)),
              const SizedBox(width: 8),
              Pill('${s(o['distance_km'])} km · ETA ${s(o['eta_for_you'])} min', color: C.cyan),
              const SizedBox(width: 8),
              Pill('priority ${s(m(o['priority'])['score'])}', color: C.violet2),
            ]),
            unitPhoto(o['photo']),
            const SizedBox(height: 22),
            const Text('WHY YOU', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
            const SizedBox(height: 8),
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final w in l(o['why']))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      const Icon(Icons.check_circle_rounded, size: 16, color: C.ok),
                      const SizedBox(width: 10),
                      Expanded(child: Text(s(w), style: const TextStyle(height: 1.4))),
                    ]),
                  ),
              ]),
            ),
            const Spacer(),
            if (_error != null) Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(_error!, style: const TextStyle(color: C.red))),
            if (_waiting)
              const Panel(
                color: C.deep,
                border: C.violet,
                child: Row(children: [
                  SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: C.violet2)),
                  SizedBox(width: 14),
                  Expanded(child: Text('You accepted. Everyone nearby was notified, so we are choosing the best match…', style: TextStyle(height: 1.4))),
                ]),
              )
            else ...[
            FilledButton.icon(
              onPressed: _busy
                  ? null
                  : () async {
                      if (await confirmDialog(context, title: 'Accept this job?', body: 'You are committing to go to ${s(widget.offer['site'])}. If another technician is a better match, you will be told.', yes: 'Yes, accept')) _answer('accept');
                    },
              icon: const Icon(Icons.check_rounded),
              label: const Text('Accept and go'),
              style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 18), minimumSize: const Size.fromHeight(56)),
            ),
            const SizedBox(height: 10),
            OutlinedButton(onPressed: _busy ? null : () async {
              if (await confirmDialog(context, title: 'Reject this job?', body: 'It will be offered to the next technicians.', yes: 'Yes, reject')) _answer('decline');
            }, style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)), child: const Text('Decline')),
            ],
          ]),
        ),
      ),
    );
  }
}
