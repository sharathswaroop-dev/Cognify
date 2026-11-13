import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import 'api.dart';
import 'theme.dart';

String s(dynamic v) => v == null ? '' : v.toString();
List<dynamic> l(dynamic v) => v is List ? v : const [];
Map<String, dynamic> m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

// ============================================================ the job list
class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  List<dynamic> _jobs = const [];
  String? _error;
  bool _loading = true;

  Timer? _refresh;

  @override
  void initState() {
    super.initState();
    _load();
    _refresh = Timer.periodic(const Duration(seconds: 5), (_) => _load(quiet: true));
  }

  @override
  void dispose() {
    _refresh?.cancel();
    super.dispose();
  }

  Future<void> _load({bool quiet = false}) async {
    if (!quiet) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final tid = s(Api.user?['tech_id']);
      final r = l(await Api.get('/api/jobs/open${tid.isEmpty ? '' : '?technician=${Uri.encodeComponent(tid)}'}'));
      r.sort((a, b) => (m(b)['report_id'] != null ? 1 : 0).compareTo(m(a)['report_id'] != null ? 1 : 0));   // jobs dispatched to you first
      if (mounted) setState(() => _jobs = r);
    } on ApiError catch (e) {
      if (!quiet && mounted) setState(() => _error = e.message);
    } finally {
      if (mounted && !quiet) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _jobs.isEmpty) return const Center(child: CircularProgressIndicator(color: C.violet));
    if (_error != null && _jobs.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: C.red)),
            const SizedBox(height: 16),
            OutlinedButton(onPressed: _load, child: const Text('Try again')),
          ]),
        ),
      );
    }
    return RefreshIndicator(
      color: C.violet,
      backgroundColor: C.s2,
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(4, 8, 4, 14),
            child: Text('Today\'s jobs', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: -0.8)),
          ),
          for (final j in _jobs) Padding(padding: const EdgeInsets.only(bottom: 12), child: _JobCard(job: m(j))),
        ],
      ),
    );
  }
}

class _JobCard extends StatelessWidget {
  final Map<String, dynamic> job;
  const _JobCard({required this.job});

  @override
  Widget build(BuildContext context) {
    final mach = m(job['machine']), site = m(job['site']), tech = m(job['technician']);
    final high = s(job['priority']).toLowerCase() == 'high';
    return Panel(
      onTap: () async {
        final ok = await confirmDialog(context,
            title: 'Open this job?',
            body: '${s(job['symptom'])}\n${s(site['name'])}\n\nYou will see the unit\'s history, then go through arrival, the customer\'s OTP and the work.',
            yes: 'Yes, open it');
        if (ok && context.mounted) Navigator.of(context).push(MaterialPageRoute(builder: (_) => JobScreen(job: job)));
      },
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (job['report_id'] != null) ...[const Pill('Dispatched to you', color: C.violet2), const SizedBox(width: 8)],
          Pill(s(job['priority']).isEmpty ? 'Normal' : s(job['priority']), color: high ? C.red : C.cyan),
          const SizedBox(width: 8),
          Text(s(job['machine_id']), style: const TextStyle(fontWeight: FontWeight.w800, color: C.violet2)),
          const Spacer(),
          Text(s(job['date']), style: const TextStyle(color: C.dim, fontSize: 12)),
        ]),
        const SizedBox(height: 10),
        Text(s(job['symptom']), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, height: 1.35)),
        const SizedBox(height: 8),
        Text('${s(mach['model'])} · ${s(mach['location'])}', style: const TextStyle(color: C.mute, fontSize: 13)),
        const SizedBox(height: 2),
        Text(s(site['name']), style: const TextStyle(color: C.mute, fontSize: 13)),
        if (s(tech['name']).isNotEmpty) ...[
          const SizedBox(height: 10),
          Row(children: [
            const Icon(Icons.person_outline_rounded, size: 16, color: C.dim),
            const SizedBox(width: 6),
            Text('${s(tech['name'])} · ${s(tech['speciality'])}', style: const TextStyle(color: C.dim, fontSize: 12.5)),
          ]),
        ],
      ]),
    );
  }
}

// ============================================================ one job: brief me, then log it
class JobScreen extends StatefulWidget {
  final Map<String, dynamic> job;
  const JobScreen({super.key, required this.job});

  @override
  State<JobScreen> createState() => _JobScreenState();
}

class _JobScreenState extends State<JobScreen> {
  String? _runId;
  bool _running = false;
  String? _error;
  List<dynamic> _events = const [];
  Map<String, dynamic>? _briefing;
  Timer? _timer;
  Map<String, dynamic>? _report;
  Timer? _reportTimer;
  final _otp = TextEditingController();
  String? _otpError;
  bool _starting = false;

  @override
  void initState() {
    super.initState();
    if (widget.job['report_id'] != null) {
      _loadReport();
      _reportTimer = Timer.periodic(const Duration(seconds: 3), (_) => _loadReport());
    }
  }

  Future<void> _loadReport() async {
    try {
      final r = m(await Api.get('/api/reports/${s(widget.job['report_id'])}'));
      if (mounted) setState(() => _report = r);
    } catch (_) {}
  }

  Future<void> _startWork() async {
    setState(() {
      _starting = true;
      _otpError = null;
    });
    try {
      final r = m(await Api.post('/api/reports/${s(widget.job['report_id'])}/start', {'tech_id': s(Api.user?['tech_id']), 'otp': _otp.text.trim()}));
      if (mounted) {
        setState(() => _report = r);
        _otp.clear();
      }
    } on ApiError catch (e) {
      if (mounted) setState(() => _otpError = e.message);
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  /// A dispatched job can only be logged once the customer's OTP has started the work.
  bool get _canLog => _report == null || const ['working', 'resolved'].contains(s(_report!['status']));

  Future<void> _arrived() async {
    try {
      final r = m(await Api.post('/api/reports/${s(widget.job['report_id'])}/status', {'tech_id': s(Api.user?['tech_id']), 'status': 'on_site'}));
      if (mounted) setState(() => _report = r);
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _reportTimer?.cancel();
    _otp.dispose();
    super.dispose();
  }

  Future<void> _brief() async {
    final sid = widget.job['scenario_id'];
    if (sid == null) {
      setState(() => _error = 'Live agents run on the demo alarms. This job has no alarm attached.');
      return;
    }
    setState(() {
      _running = true;
      _error = null;
      _events = const [];
      _briefing = null;
    });
    try {
      final r = await Api.post('/api/runs', {'scenario_id': sid, 'paths': 'with'});
      _runId = r['run_id'] as String;
      _timer = Timer.periodic(const Duration(milliseconds: 1400), (_) => _poll());
    } on ApiError catch (e) {
      setState(() {
        _running = false;
        _error = e.message;
      });
    }
  }

  Future<void> _poll() async {
    try {
      final r = m(await Api.get('/api/runs/$_runId'));
      if (!mounted) return;
      final plans = m(r['plans']);
      final withPlan = m(plans['with']);
      setState(() {
        _events = l(r['events']);
        if (withPlan['briefing'] != null) _briefing = m(withPlan['briefing']);
      });
      if (s(r['status']) != 'running') {
        _timer?.cancel();
        setState(() => _running = false);
      }
    } on ApiError catch (e) {
      _timer?.cancel();
      if (mounted) {
        setState(() {
          _running = false;
          _error = e.message;
        });
      }
    }
  }

  static const _shown = {'handoff', 'veto', 'approve', 'revise', 'msg', 'plan'};

  @override
  Widget build(BuildContext context) {
    final job = widget.job;
    final mach = m(job['machine']), site = m(job['site']);
    final feed = _events.where((e) => _shown.contains(s(m(e)['kind']))).toList();
    return Scaffold(
      appBar: AppBar(title: Text('${s(job['machine_id'])} · ${s(job['job_id'])}')),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 32), children: [
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(s(job['symptom']), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, height: 1.35)),
            const SizedBox(height: 10),
            Text('${s(mach['model'])} · installed ${s(mach['installed'])}', style: const TextStyle(color: C.mute)),
            Text('${s(mach['location'])} · ${s(site['name'])}', style: const TextStyle(color: C.mute)),
            const SizedBox(height: 8),
            Text('Reported by ${s(job['reported_by'])}', style: const TextStyle(color: C.dim, fontSize: 12.5)),
          ]),
        ),
        if (_report != null) ...[
          const SizedBox(height: 14),
          Panel(
            color: s(_report!['status']) == 'resolved' ? const Color(0xFF0A2A1F) : C.deep,
            border: s(_report!['status']) == 'resolved' ? const Color(0xFF136B4B) : C.violet,
            child: Row(children: [
              Icon(s(_report!['status']) == 'resolved' ? Icons.check_circle_rounded : Icons.directions_car_filled_rounded, color: s(_report!['status']) == 'resolved' ? C.ok : C.cyan),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  {'en_route': 'On your way to ${s(_report!['site'])}', 'on_site': 'You are on site', 'working': 'Work in progress', 'resolved': 'Resolved. Thank you.'}[s(_report!['status'])] ?? s(_report!['status']),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              if (s(_report!['status']) == 'en_route') FilledButton(onPressed: () async {
                if (await confirmDialog(context, title: 'Confirm you have arrived?', body: 'The customer will be asked for their OTP to start the work.', yes: 'Yes, I am here')) _arrived();
              }, style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10)), child: const Text("I've arrived")),
            ]),
          ),
        ],
        if (_report != null && s(_report!['status']) == 'on_site') ...[
          const SizedBox(height: 12),
          Panel(
            color: C.deep,
            border: C.violet,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('ASK THE CUSTOMER FOR THEIR OTP', style: TextStyle(color: C.violet2, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
              const SizedBox(height: 6),
              const Text('The customer sees a 4-digit code in their app. Enter it to start the work. It proves you are on site.', style: TextStyle(color: C.mute, height: 1.4)),
              const SizedBox(height: 12),
              TextField(
                controller: _otp,
                keyboardType: TextInputType.number,
                maxLength: 4,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w800, letterSpacing: 14),
                decoration: const InputDecoration(counterText: '', hintText: '••••'),
                onSubmitted: (_) => _startWork(),
              ),
              if (_otpError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_otpError!, style: const TextStyle(color: C.red))),
              const SizedBox(height: 12),
              FilledButton.icon(onPressed: _starting ? null : _startWork, icon: const Icon(Icons.play_arrow_rounded), label: const Text('Start work'), style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50))),
            ]),
          ),
        ],
        const SizedBox(height: 14),
        FilledButton.icon(
          onPressed: _running ? null : _brief,
          icon: _running
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2, color: Colors.white))
              : const Icon(Icons.hub_rounded),
          label: Text(_running ? 'The agents are working…' : (_briefing == null ? 'Brief me: run the four agents' : 'Run it again')),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Panel(color: const Color(0xFF2E1018), border: const Color(0xFF7A2638), child: Text(_error!, style: const TextStyle(color: C.red))),
        ],
        if (feed.isNotEmpty) ...[
          const SizedBox(height: 18),
          const Text('IN THE BAND ROOM', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 1.2)),
          const SizedBox(height: 8),
          for (final e in feed) _EventTile(event: m(e)),
        ],
        if (_briefing != null) ...[
          const SizedBox(height: 18),
          _BriefingCard(b: _briefing!),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: !_canLog
                ? null
                : () async {
                    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => LogScreen(job: job, briefing: _briefing)));
                    _loadReport();
                  },
            icon: const Icon(Icons.edit_note_rounded),
            label: Text(_canLog ? 'Log this visit' : 'Log this visit (start the work with the OTP first)'),
          ),
        ] else if (!_running && feed.isEmpty) ...[
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: !_canLog ? null : () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => LogScreen(job: job, briefing: null))),
            icon: const Icon(Icons.edit_note_rounded),
            label: const Text('Log a visit without a briefing'),
          ),
        ],
      ]),
    );
  }
}

class _EventTile extends StatelessWidget {
  final Map<String, dynamic> event;
  const _EventTile({required this.event});

  @override
  Widget build(BuildContext context) {
    final agent = s(event['agent']);
    final kind = s(event['kind']);
    final color = kind == 'veto' ? C.red : (kind == 'approve' ? C.ok : agentColor(agent));
    var text = s(event['text']);
    if (text.length > 230) text = '${text.substring(0, 227)}…';
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: C.s2,
        borderRadius: BorderRadius.circular(14),
        border: Border(left: BorderSide(color: color, width: 3)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(s(event['label']).isEmpty ? agent : s(event['label']), style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12.5)),
          const SizedBox(width: 8),
          if (kind == 'veto') const Pill('veto', color: C.red),
          if (kind == 'approve') const Pill('approved', color: C.ok),
          if (kind == 'handoff') const Pill('handoff', color: C.cyan),
        ]),
        const SizedBox(height: 6),
        Text(text, style: const TextStyle(fontSize: 13.5, height: 1.4)),
      ]),
    );
  }
}

class _BriefingCard extends StatelessWidget {
  final Map<String, dynamic> b;
  const _BriefingCard({required this.b});

  @override
  Widget build(BuildContext context) {
    final conf = s(b['confidence']);
    return Panel(
      color: C.deep,
      border: C.violet,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('TECHNICIAN BRIEFING', style: TextStyle(color: C.violet2, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
        const SizedBox(height: 8),
        Text(s(b['headline']), style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800, height: 1.25, letterSpacing: -0.4)),
        const SizedBox(height: 10),
        Row(children: [Pill(conf, color: confidenceColor(conf))]),
        if (s(b['evidence']).isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(s(b['evidence']), style: const TextStyle(color: C.mute, fontSize: 12.5, height: 1.4)),
        ],
        const SizedBox(height: 10),
        Text(s(b['likely_cause']), style: const TextStyle(color: C.text, height: 1.45)),
        _section('DO FIRST', C.ok, l(b['do_first']), numbered: true),
        _section('DO NOT REPEAT', C.red, l(b['avoid'])),
        if (l(b['bring']).isNotEmpty) ...[
          const SizedBox(height: 14),
          const Text('BRING', style: TextStyle(color: C.amber, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [for (final p in l(b['bring'])) Pill(s(p), color: C.amber)]),
        ],
        _section('AT THE SITE', C.cyan, l(b['site_notes'])),
      ]),
    );
  }

  Widget _section(String title, Color color, List<dynamic> items, {bool numbered = false}) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(color: color, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
        const SizedBox(height: 6),
        for (var i = 0; i < items.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 5),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 22, child: Text(numbered ? '${i + 1}.' : '•', style: TextStyle(color: color, fontWeight: FontWeight.w800))),
              Expanded(child: Text(s(items[i]), style: const TextStyle(height: 1.4))),
            ]),
          ),
      ]),
    );
  }
}

// ============================================================ log the visit: typed or spoken, then confirm
class LogScreen extends StatefulWidget {
  final Map<String, dynamic> job;
  final Map<String, dynamic>? briefing;
  const LogScreen({super.key, required this.job, required this.briefing});

  @override
  State<LogScreen> createState() => _LogScreenState();
}

class _LogScreenState extends State<LogScreen> {
  final _rec = AudioRecorder();
  final _cause = TextEditingController();
  final _notes = TextEditingController();
  final _parts = TextEditingController();
  final List<_Attempt> _attempts = [];
  String _outcome = 'resolved';
  bool _recording = false;
  bool _working = false;
  bool _saving = false;
  String? _msg;
  String? _transcript;

  @override
  void initState() {
    super.initState();
    final top = l(widget.briefing?['do_first']);
    _attempts.add(_Attempt(text: top.isNotEmpty ? s(top.first) : '', result: 'worked'));
  }

  @override
  void dispose() {
    _rec.dispose();
    _cause.dispose();
    _notes.dispose();
    _parts.dispose();
    for (final a in _attempts) {
      a.ctl.dispose();
    }
    super.dispose();
  }

  Future<void> _toggleRecord() async {
    if (_recording) {
      final path = await _rec.stop();
      setState(() {
        _recording = false;
        _working = true;
        _msg = 'Transcribing…';
      });
      if (path == null) {
        setState(() {
          _working = false;
          _msg = 'The recording could not be saved.';
        });
        return;
      }
      try {
        final r = m(await Api.upload('/api/voice/report', {'job_id': s(widget.job['job_id'])}, 'audio', path));
        _fill(m(r['structured']));
        setState(() {
          _transcript = s(r['transcript']);
          final w = l(r['warnings']);
          _msg = w.isNotEmpty ? s(w.first) : 'Check what I heard, fix anything wrong, then save.';
        });
      } on ApiError catch (e) {
        setState(() => _msg = e.message);
      } finally {
        if (mounted) setState(() => _working = false);
      }
      return;
    }
    if (!await _rec.hasPermission()) {
      setState(() => _msg = 'Allow the microphone in Settings to speak your report.');
      return;
    }
    final dir = await getTemporaryDirectory();
    await _rec.start(const RecordConfig(encoder: AudioEncoder.aacLc), path: '${dir.path}/visit_${DateTime.now().millisecondsSinceEpoch}.m4a');
    setState(() {
      _recording = true;
      _msg = 'Listening… say what you tried, what worked, and what you found. Tap again to stop.';
    });
  }

  void _fill(Map<String, dynamic> st) {
    for (final a in _attempts) {
      a.ctl.dispose();
    }
    _attempts.clear();
    for (final a in l(st['actions'])) {
      final am = m(a);
      _attempts.add(_Attempt(text: s(am['action']), result: ['worked', 'failed', 'partial'].contains(s(am['result'])) ? s(am['result']) : 'failed'));
    }
    if (_attempts.isEmpty) _attempts.add(_Attempt(text: '', result: 'failed'));
    _outcome = s(st['outcome']) == 'resolved' ? 'resolved' : 'revisit_needed';
    _cause.text = s(st['root_cause']);
    _notes.text = s(st['notes']);
    _parts.text = l(st['parts_used']).map(s).join(', ');
  }

  Future<void> _save() async {
    final acts = _attempts.where((a) => a.ctl.text.trim().length >= 2).toList();
    if (acts.isEmpty) {
      setState(() => _msg = 'Write at least one thing you tried.');
      return;
    }
    setState(() {
      _saving = true;
      _msg = null;
    });
    try {
      final top = l(widget.briefing?['do_first']);
      final r = m(await Api.post('/api/jobs/${s(widget.job['job_id'])}/log', {
        'actions': [for (final a in acts) {'action': a.ctl.text.trim(), 'result': a.result, 'detail': ''}],
        'outcome': _outcome,
        'root_cause': _cause.text.trim(),
        'suspected_cause': top.isNotEmpty ? s(top.first) : '',
        'parts_used': _parts.text.split(',').map((x) => x.trim()).where((x) => x.isNotEmpty).toList(),
        'notes': _notes.text.trim(),
        'machine_id': s(widget.job['machine_id']),
      }));
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: C.s2,
          title: const Text('Saved to the company memory'),
          content: Text('${s(r['memory_text'])}\n\nThe next briefing for ${s(widget.job['machine_id'])} will use this.', style: const TextStyle(color: C.mute, height: 1.45)),
          actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Done'))],
        ),
      );
      if (mounted) Navigator.of(context).pop();
    } on ApiError catch (e) {
      setState(() => _msg = e.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Log the visit')),
        body: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 40), children: [
          Panel(
            color: _recording ? const Color(0xFF2E1018) : C.s1,
            border: _recording ? C.red : C.line,
            child: Column(children: [
              Row(children: [
                GestureDetector(
                  onTap: _working ? null : _toggleRecord,
                  child: Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(shape: BoxShape.circle, color: _recording ? C.red : C.violet),
                    child: Icon(_recording ? Icons.stop_rounded : Icons.mic_rounded, size: 30, color: Colors.white),
                  ),
                ),
                const SizedBox(width: 14),
                const Expanded(child: Text('Speak your report', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700))),
                if (_working) const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: C.violet)),
              ]),
              if (_msg != null) ...[
                const SizedBox(height: 12),
                Align(alignment: Alignment.centerLeft, child: Text(_msg!, style: const TextStyle(color: C.mute, height: 1.4))),
              ],
              if (_transcript != null && _transcript!.isNotEmpty) ...[
                const SizedBox(height: 10),
                Align(alignment: Alignment.centerLeft, child: Text('“$_transcript”', style: const TextStyle(color: C.dim, fontStyle: FontStyle.italic, height: 1.4))),
              ],
            ]),
          ),
          const SizedBox(height: 18),
          const Text('WHAT YOU TRIED', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
          const SizedBox(height: 8),
          for (var i = 0; i < _attempts.length; i++) _attemptRow(i),
          TextButton.icon(
            onPressed: () => setState(() => _attempts.add(_Attempt(text: '', result: 'failed'))),
            icon: const Icon(Icons.add_rounded, color: C.violet2),
            label: const Text('Add another attempt', style: TextStyle(color: C.violet2)),
          ),
          const SizedBox(height: 10),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'resolved', label: Text('Fixed'), icon: Icon(Icons.check_circle_outline)),
              ButtonSegment(value: 'revisit_needed', label: Text('Not fixed'), icon: Icon(Icons.replay_rounded)),
            ],
            selected: {_outcome},
            onSelectionChanged: (v) => setState(() => _outcome = v.first),
          ),
          const SizedBox(height: 14),
          TextField(controller: _cause, decoration: const InputDecoration(labelText: 'Real cause (if you found it)')),
          const SizedBox(height: 12),
          TextField(controller: _parts, decoration: const InputDecoration(labelText: 'Parts used (comma separated)')),
          const SizedBox(height: 12),
          TextField(controller: _notes, maxLines: 3, decoration: const InputDecoration(labelText: 'Notes for the next person')),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2, color: Colors.white)) : const Icon(Icons.save_rounded),
            label: const Text('Save to memory'),
          ),
          const SizedBox(height: 10),
          const Text('A failed fix is just as useful as a good one: the memory learns from both.', textAlign: TextAlign.center, style: TextStyle(color: C.dim, fontSize: 12.5)),
        ]),
      );

  Widget _attemptRow(int i) {
    final a = _attempts[i];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Panel(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          TextField(controller: a.ctl, maxLines: 2, minLines: 1, decoration: const InputDecoration(hintText: 'e.g. Replaced the compressor contactor')),
          const SizedBox(height: 10),
          Row(children: [
            for (final r in const ['worked', 'partial', 'failed'])
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(r[0].toUpperCase() + r.substring(1)),
                  selected: a.result == r,
                  selectedColor: r == 'worked' ? C.ok.withValues(alpha: 0.28) : (r == 'failed' ? C.red.withValues(alpha: 0.28) : C.amber.withValues(alpha: 0.28)),
                  backgroundColor: C.s2,
                  side: const BorderSide(color: C.line2),
                  onSelected: (_) => setState(() => a.result = r),
                ),
              ),
            const Spacer(),
            if (_attempts.length > 1)
              IconButton(
                onPressed: () => setState(() {
                  _attempts.removeAt(i).ctl.dispose();
                }),
                icon: const Icon(Icons.close_rounded, color: C.dim, size: 20),
              ),
          ]),
        ]),
      ),
    );
  }
}

class _Attempt {
  final TextEditingController ctl;
  String result;
  _Attempt({required String text, required this.result}) : ctl = TextEditingController(text: text);
}

// keep the File import used on all platforms
// ignore: unused_element
bool _fileExists(String p) => File(p).existsSync();
