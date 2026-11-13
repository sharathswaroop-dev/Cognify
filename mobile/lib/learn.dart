import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'jobs.dart';
import 'theme.dart';

/// Watch the memory learn: each incident answered from only the records before it, with and without memory.
class LearnScreen extends StatefulWidget {
  const LearnScreen({super.key});

  @override
  State<LearnScreen> createState() => _LearnScreenState();
}

class _LearnScreenState extends State<LearnScreen> {
  List<Map<String, dynamic>> _steps = const [];
  int _i = 1;
  bool _playing = false;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = m(await Api.get('/api/learning'));
      if (mounted) setState(() => _steps = l(r['steps']).map(m).toList());
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _toggle() {
    if (_playing) {
      _timer?.cancel();
      setState(() => _playing = false);
      return;
    }
    if (_i >= _steps.length) _i = 1;
    setState(() => _playing = true);
    _schedule();
  }

  void _schedule() {
    final cur = _steps[_i - 1];
    final slow = cur['belief_event'] != null || (m(cur['with_memory'])['abstained'] == true && (cur['records_known'] ?? 0) > 0);
    _timer = Timer(Duration(milliseconds: slow ? 3800 : 1500), () {
      if (!mounted) return;
      if (_i >= _steps.length) {
        setState(() => _playing = false);
        return;
      }
      setState(() => _i++);
      _schedule();
    });
  }

  Color _kindColor(Map<String, dynamic> st) {
    final w = m(st['with_memory']);
    if (w['hit'] == true) return C.ok;
    if (w['abstained'] == true) return C.amber;
    return C.red;
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) return Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error!, style: const TextStyle(color: C.red), textAlign: TextAlign.center)));
    if (_steps.isEmpty) return const Center(child: CircularProgressIndicator(color: C.violet));
    final st = _steps[_i - 1];
    final w = m(st['with_memory']);
    final score = m(st['score']);
    final conf = s(w['confidence']);
    final n = (w['n'] ?? 0) as num;
    final ver = (w['verified'] ?? 0) as num;
    final belief = st['belief_event'];
    final abstained = w['abstained'] == true;
    return ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 28), children: [
      const Padding(
        padding: EdgeInsets.fromLTRB(4, 8, 4, 4),
        child: Text('Watch it learn', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: -0.8)),
      ),
      const Padding(
        padding: EdgeInsets.fromLTRB(4, 0, 4, 14),
        child: Text('Every incident is answered using only the records dated before it.', style: TextStyle(color: C.mute, height: 1.4)),
      ),
      Row(children: [
        Expanded(child: _Score(label: 'Without memory', value: '${score['without']}', total: '${score['of']}', color: C.dim)),
        const SizedBox(width: 10),
        Expanded(child: _Score(label: 'With memory', value: '${score['memory']}', total: '${score['of']}', color: C.cyan)),
      ]),
      const SizedBox(height: 12),
      Wrap(spacing: 4, runSpacing: 4, children: [
        for (var k = 1; k <= _steps.length; k++)
          GestureDetector(
            onTap: () => setState(() {
              _timer?.cancel();
              _playing = false;
              _i = k;
            }),
            child: Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                color: k <= _i ? _kindColor(_steps[k - 1]) : C.s2,
                borderRadius: BorderRadius.circular(6),
                border: k == _i ? Border.all(color: C.violet2, width: 2) : null,
              ),
            ),
          ),
      ]),
      const SizedBox(height: 14),
      Panel(
        color: C.deep,
        border: C.violet,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Incident ${st['i']} of ${_steps.length} · ${s(st['date'])}', style: const TextStyle(color: C.mute, fontSize: 12.5)),
          const SizedBox(height: 4),
          Text('${s(st['machine_id'])} · ${s(st['model'])} · installed ${s(st['installed'])}', style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Text(abstained ? 'No precedent on record: escalate to a senior technician.' : s(w['fix']), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, height: 1.3)),
          const SizedBox(height: 10),
          Row(children: [
            Pill(conf == 'weak' ? 'weak signal' : '$conf confidence', color: confidenceColor(conf)),
            const SizedBox(width: 8),
            Pill(w['hit'] == true ? 'RIGHT' : (abstained ? 'SAID SO' : 'WRONG'), color: _kindColor(st)),
          ]),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(value: n > 0 ? (ver / n).toDouble() : 0, minHeight: 8, color: C.cyan, backgroundColor: C.s3),
          ),
          const SizedBox(height: 6),
          Text(n > 0 ? '$ver of $n past attempts verified stable' : 'Nothing in the records to count yet.', style: const TextStyle(color: C.mute, fontSize: 12.5)),
          const SizedBox(height: 12),
          Text('Memory holds ${st['records_known']} raw records.', style: const TextStyle(color: C.dim, fontSize: 12.5)),
        ]),
      ),
      const SizedBox(height: 12),
      Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('WHAT ACTUALLY FIXED IT', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
          const SizedBox(height: 6),
          Text(s(m(st['truth'])['fix']).isEmpty ? 'unknown' : s(m(st['truth'])['fix']), style: const TextStyle(height: 1.4)),
        ]),
      ),
      if (belief != null) ...[
        const SizedBox(height: 12),
        Panel(
          color: const Color(0xFF2A2160),
          border: C.violet2,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('THE MEMORY CORRECTED ITSELF', style: TextStyle(color: C.violet2, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
            const SizedBox(height: 6),
            Text(s(m(belief)['text']), style: const TextStyle(height: 1.45)),
          ]),
        ),
      ] else if (abstained && (st['records_known'] ?? 0) > 0) ...[
        const SizedBox(height: 12),
        const Panel(
          color: Color(0xFF241B08),
          border: Color(0xFF7A5A12),
          child: Text('New kind of fault. Nothing in the records fixes this on units like this one, so it says so instead of guessing, and it learns from this visit.', style: TextStyle(height: 1.45)),
        ),
      ],
      const SizedBox(height: 16),
      Row(children: [
        Expanded(
          child: FilledButton.icon(onPressed: _toggle, icon: Icon(_playing ? Icons.pause_rounded : Icons.play_arrow_rounded), label: Text(_playing ? 'Pause' : 'Play')),
        ),
        const SizedBox(width: 10),
        OutlinedButton(
          onPressed: () => setState(() {
            _timer?.cancel();
            _playing = false;
            _i = (_i - 1).clamp(1, _steps.length);
          }),
          child: const Icon(Icons.chevron_left_rounded),
        ),
        const SizedBox(width: 8),
        OutlinedButton(
          onPressed: () => setState(() {
            _timer?.cancel();
            _playing = false;
            _i = (_i + 1).clamp(1, _steps.length);
          }),
          child: const Icon(Icons.chevron_right_rounded),
        ),
      ]),
    ]);
  }
}

class _Score extends StatelessWidget {
  final String label, value, total;
  final Color color;
  const _Score({required this.label, required this.value, required this.total, required this.color});

  @override
  Widget build(BuildContext context) => Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label.toUpperCase(), style: const TextStyle(color: C.mute, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 1.1)),
          const SizedBox(height: 6),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(value, style: TextStyle(fontSize: 38, fontWeight: FontWeight.w800, color: color, height: 1)),
            const SizedBox(width: 6),
            Text('of $total right', style: const TextStyle(color: C.dim, fontSize: 12.5)),
          ]),
        ]),
      );
}
