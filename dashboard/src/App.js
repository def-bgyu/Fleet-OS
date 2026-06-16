import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';
import './App.css';

const REGISTRY_URL = process.env.REACT_APP_REGISTRY_URL || 'http://localhost:8000';
const SCHEDULER_URL = process.env.REACT_APP_SCHEDULER_URL || 'http://localhost:8001';
const MANAGER_URL = process.env.REACT_APP_MANAGER_URL || 'http://localhost:8002';
const SESSION_URL = process.env.REACT_APP_SESSION_URL || 'http://localhost:8003';
const REFRESH_INTERVAL = 3000;
const SESSION_HEARTBEAT_INTERVAL = 60000; // ping session service every 60s to stay alive
const MAX_HISTORY = 20;

const NODE_COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#10b981', '#f43f5e', '#a78bfa', '#34d399', '#fb923c'];

// Axios instance that auto-attaches session token header
function makeApi(sessionToken) {
  return axios.create({
    headers: { 'x-session-token': sessionToken }
  });
}

// ============================================================
// SESSION GATE — shown before a session is started
// ============================================================
function SessionGate({ onSessionStart }) {
  const [sessionCount, setSessionCount] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchCount = async () => {
      try {
        const res = await axios.get(`${SESSION_URL}/sessions/count`);
        setSessionCount(res.data);
      } catch {
        setSessionCount(null);
      }
    };
    fetchCount();
    const interval = setInterval(fetchCount, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.post(`${SESSION_URL}/sessions/create`);
      const { session_id } = res.data;
      sessionStorage.setItem('fleetos_session_id', session_id);
      onSessionStart(session_id);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to start session';
      setError(msg);
    }
    setLoading(false);
  };

  const slotsLeft = sessionCount ? sessionCount.slots_available : null;
  const isFull = slotsLeft === 0;

  return (
    <div style={{
      minHeight: '100vh', background: '#080810', display: 'flex',
      alignItems: 'center', justifyContent: 'center', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    }}>
      <div style={{
        background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '16px',
        padding: '48px', maxWidth: '440px', width: '100%', textAlign: 'center'
      }}>
        {/* Logo */}
        <div style={{
          width: '56px', height: '56px', background: 'linear-gradient(135deg, #6366f1, #22d3ee)',
          borderRadius: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '26px', margin: '0 auto 24px'
        }}>⚡</div>

        <div style={{ color: '#fff', fontSize: '22px', fontWeight: '700', marginBottom: '8px' }}>FleetOS</div>
        <div style={{ color: '#444', fontSize: '13px', marginBottom: '32px' }}>
          AI Inference Fleet Management
        </div>

        {/* Session count indicator */}
        <div style={{
          background: '#111118', border: '1px solid #1f1f2e', borderRadius: '10px',
          padding: '14px 20px', marginBottom: '28px', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center'
        }}>
          <span style={{ color: '#555', fontSize: '12px' }}>Live sessions</span>
          {sessionCount ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ display: 'flex', gap: '4px' }}>
                {Array.from({ length: sessionCount.max_sessions }).map((_, i) => (
                  <div key={i} style={{
                    width: '10px', height: '10px', borderRadius: '50%',
                    background: i < sessionCount.active_sessions ? '#6366f1' : '#1f1f2e'
                  }} />
                ))}
              </div>
              <span style={{ color: isFull ? '#f43f5e' : '#888', fontSize: '12px' }}>
                {sessionCount.active_sessions}/{sessionCount.max_sessions}
              </span>
            </div>
          ) : (
            <span style={{ color: '#333', fontSize: '12px' }}>checking...</span>
          )}
        </div>

        {error && (
          <div style={{
            background: '#1a0808', border: '1px solid #f43f5e33', borderRadius: '8px',
            padding: '10px 14px', marginBottom: '20px', color: '#f43f5e', fontSize: '12px'
          }}>{error}</div>
        )}

        <button
          onClick={handleStart}
          disabled={loading || isFull}
          style={{
            width: '100%', padding: '14px', borderRadius: '10px', border: 'none',
            background: isFull ? '#1a1a2e' : 'linear-gradient(135deg, #6366f1, #22d3ee)',
            color: isFull ? '#333' : '#fff', fontSize: '14px', fontWeight: '600',
            cursor: isFull ? 'not-allowed' : 'pointer', transition: 'opacity 0.2s',
            opacity: loading ? 0.7 : 1
          }}
        >
          {loading ? 'Starting session...' : isFull ? 'All sessions in use — try again later' : 'Start Session'}
        </button>

        <div style={{ color: '#2a2a3a', fontSize: '11px', marginTop: '20px', lineHeight: '1.6' }}>
          Each session is isolated — up to 6 nodes, 10 min idle timeout.
        </div>
      </div>
    </div>
  );
}

// ============================================================
// SIDEBAR
// ============================================================
function Sidebar({ active, setActive, onEndSession }) {
  const items = [
    { id: 'overview', icon: '◈', label: 'Overview' },
    { id: 'nodes', icon: '⬡', label: 'Nodes' },
    { id: 'jobs', icon: '⚡', label: 'Jobs' },
    { id: 'metrics', icon: '◎', label: 'Metrics' },
  ];
  return (
    <div style={{
      width: '220px', minHeight: '100vh', background: '#0c0c0f',
      borderRight: '1px solid #1f1f2e', padding: '0', flexShrink: 0,
      display: 'flex', flexDirection: 'column'
    }}>
      <div style={{ padding: '24px 20px', borderBottom: '1px solid #1f1f2e' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '32px', height: '32px', background: 'linear-gradient(135deg, #6366f1, #22d3ee)',
            borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '16px'
          }}>⚡</div>
          <div>
            <div style={{ color: '#fff', fontSize: '15px', fontWeight: '600' }}>FleetOS</div>
            <div style={{ color: '#444', fontSize: '10px' }}>v1.0.0</div>
          </div>
        </div>
      </div>

      <nav style={{ padding: '12px 10px', flex: 1 }}>
        {items.map(item => (
          <div key={item.id} onClick={() => setActive(item.id)} style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            padding: '10px 12px', borderRadius: '8px', cursor: 'pointer', marginBottom: '2px',
            background: active === item.id ? '#1a1a2e' : 'transparent',
            color: active === item.id ? '#6366f1' : '#555',
            transition: 'all 0.15s ease', fontSize: '13px'
          }}>
            <span style={{ fontSize: '16px' }}>{item.icon}</span>
            {item.label}
          </div>
        ))}
      </nav>

      <div style={{ padding: '16px', borderTop: '1px solid #1f1f2e' }}>
        <button onClick={onEndSession} style={{
          width: '100%', background: 'transparent', border: '1px solid #2a1a1a',
          color: '#f43f5e', borderRadius: '7px', padding: '8px', fontSize: '11px', cursor: 'pointer'
        }}>End Session</button>
        <div style={{ color: '#222', fontSize: '10px', marginTop: '10px' }}>AI Inference Fleet Management</div>
      </div>
    </div>
  );
}

// ============================================================
// SHARED COMPONENTS (unchanged visually)
// ============================================================
function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px',
      padding: '20px', flex: 1, minWidth: '120px'
    }}>
      <div style={{ color: '#444', fontSize: '11px', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1px' }}>{label}</div>
      <div style={{ color: color || '#fff', fontSize: '28px', fontWeight: '700', marginBottom: '4px' }}>{value}</div>
      {sub && <div style={{ color: '#333', fontSize: '11px' }}>{sub}</div>}
    </div>
  );
}

function NodeCard({ node, onKill, onRestart, onRemove }) {
  const isHealthy = node.status === 'healthy';
  const isDead = node.status === 'dead';
  const isStarting = node.status === 'starting';
  const isRecovering = node.status === 'recovering';
  return (
    <div style={{
      background: '#0c0c0f',
      border: `1px solid ${isHealthy ? '#1f1f2e' : isDead ? '#3a1a1a' : '#2a2010'}`,
      borderRadius: '12px', padding: '18px', transition: 'all 0.2s ease'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{
            width: '8px', height: '8px', borderRadius: '50%',
            background: isHealthy ? '#10b981' : isDead ? '#f43f5e' : isStarting ? '#6366f1' : '#f59e0b',
            animation: isHealthy ? 'pulse 2s infinite' : 'none',
            boxShadow: isHealthy ? '0 0 6px #10b981' : 'none'
          }} />
          <span style={{ color: '#fff', fontSize: '13px', fontWeight: '600' }}>{node.node_id}</span>
        </div>
        <span style={{
          fontSize: '10px', padding: '2px 8px', borderRadius: '20px',
          background: isHealthy ? '#0d2818' : isDead ? '#2a0d0d' : '#2a1f0d',
          color: isHealthy ? '#10b981' : isDead ? '#f43f5e' : '#f59e0b',
          border: `1px solid ${isHealthy ? '#10b981' : isDead ? '#f43f5e' : '#f59e0b'}33`
        }}>{node.status}</span>
      </div>

      {isHealthy && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '14px' }}>
          {[
            { label: 'CPU', value: `${node.cpu?.toFixed(1)}%`, color: node.cpu > 70 ? '#f59e0b' : '#6366f1' },
            { label: 'Latency', value: `${node.inference_latency_ms?.toFixed(1)}ms`, color: '#22d3ee' },
            { label: 'Jobs', value: node.jobs_processed, color: '#10b981' },
            { label: 'Model', value: node.model_version || 'v1.0', color: '#a78bfa' },
          ].map(s => (
            <div key={s.label} style={{ background: '#111118', borderRadius: '8px', padding: '8px 10px' }}>
              <div style={{ color: '#333', fontSize: '9px', marginBottom: '3px', textTransform: 'uppercase' }}>{s.label}</div>
              <div style={{ color: s.color, fontSize: '13px', fontWeight: '600' }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {isDead && (
        <div style={{ color: '#f43f5e', fontSize: '12px', marginBottom: '14px', padding: '8px', background: '#1a0808', borderRadius: '8px' }}>
          Heartbeat lost — self-healer active
        </div>
      )}
      {isRecovering && (
        <div style={{ color: '#f59e0b', fontSize: '12px', marginBottom: '14px', padding: '8px', background: '#1a1208', borderRadius: '8px' }}>
          Recovering — restart to bring back online or remove to free slot
        </div>
      )}
      {isStarting && (
        <div style={{ color: '#6366f1', fontSize: '12px', marginBottom: '14px', padding: '8px', background: '#0d0d2a', borderRadius: '8px' }}>
          Node booting — waiting for first heartbeat...
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px' }}>
        {isHealthy && (
          <button onClick={() => onKill(node.node_id)} style={{
            flex: 1, background: 'transparent', border: '1px solid #f43f5e33',
            color: '#f43f5e', borderRadius: '6px', padding: '6px', fontSize: '11px', cursor: 'pointer'
          }}>Kill Node</button>
        )}
        {(isDead || isRecovering) && (
          <>
            <button onClick={() => onRestart(node.node_id)} style={{
              flex: 1, background: 'transparent', border: '1px solid #10b98133',
              color: '#10b981', borderRadius: '6px', padding: '6px', fontSize: '11px', cursor: 'pointer'
            }}>Restart</button>
            <button onClick={() => onRemove(node.node_id)} style={{
              flex: 1, background: 'transparent', border: '1px solid #f59e0b33',
              color: '#f59e0b', borderRadius: '6px', padding: '6px', fontSize: '11px', cursor: 'pointer'
            }}>Remove</button>
          </>
        )}
      </div>
    </div>
  );
}

function ActivityLog({ logs }) {
  const bottomRef = useRef(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [logs]);
  return (
    <div style={{
      background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px',
      padding: '16px', height: '220px', overflowY: 'auto'
    }}>
      {logs.length === 0
        ? <span style={{ color: '#222', fontSize: '12px' }}>No activity yet...</span>
        : logs.map((log, i) => (
          <div key={i} style={{ marginBottom: '5px', fontSize: '12px', display: 'flex', gap: '10px' }}>
            <span style={{ color: '#2a2a3a', flexShrink: 0 }}>{log.time}</span>
            <span style={{ color: log.color || '#555' }}>{log.message}</span>
          </div>
        ))
      }
      <div ref={bottomRef} />
    </div>
  );
}

// ============================================================
// PAGES
// ============================================================
function OverviewPage({ summary, queueLength, logs, nodes, onKill, onRestart, onRemove, maxNodes }) {
  const pieData = [
    { name: 'Healthy', value: summary.healthy || 0 },
    { name: 'Dead', value: summary.dead || 0 },
    { name: 'Recovering', value: (summary.total_nodes || 0) - (summary.healthy || 0) - (summary.dead || 0) }
  ].filter(d => d.value > 0);
  const PIE_COLORS = ['#10b981', '#f43f5e', '#f59e0b'];

  return (
    <div>
      <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', flexWrap: 'wrap' }}>
        <StatCard label="Total Nodes" value={summary.total_nodes || 0} color="#fff" sub={`${maxNodes} max`} />
        <StatCard label="Healthy" value={summary.healthy || 0} color="#10b981" />
        <StatCard label="Dead" value={summary.dead || 0} color="#f43f5e" />
        <StatCard label="Avg CPU" value={`${summary.avg_cpu || 0}%`} color="#6366f1" />
        <StatCard label="Avg Latency" value={`${summary.avg_latency_ms || 0}ms`} color="#22d3ee" />
        <StatCard label="Queue" value={queueLength} color="#a78bfa" sub="jobs waiting" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
        <div style={{ background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px', padding: '20px' }}>
          <div style={{ color: '#888', fontSize: '11px', marginBottom: '16px', textTransform: 'uppercase', letterSpacing: '1px' }}>Fleet Health</div>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
                  {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: '8px', color: '#fff' }} />
                <Legend wrapperStyle={{ color: '#888', fontSize: '12px' }} />
              </PieChart>
            </ResponsiveContainer>
          ) : <div style={{ color: '#222', fontSize: '12px', textAlign: 'center', paddingTop: '60px' }}>No nodes yet</div>}
        </div>

        <div style={{ background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px', padding: '20px' }}>
          <div style={{ color: '#888', fontSize: '11px', marginBottom: '16px', textTransform: 'uppercase', letterSpacing: '1px' }}>Activity Log</div>
          <ActivityLog logs={logs} />
        </div>
      </div>

      <div style={{ background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px', padding: '20px' }}>
        <div style={{ color: '#888', fontSize: '11px', marginBottom: '16px', textTransform: 'uppercase', letterSpacing: '1px' }}>Fleet Nodes</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
          {nodes.length === 0
            ? <div style={{ color: '#222', fontSize: '12px' }}>No nodes — click "+ Add Node" to get started</div>
            : nodes.map((node) => <NodeCard key={node.node_id} node={node} onKill={onKill} onRestart={onRestart} onRemove={onRemove} />)
          }
        </div>
      </div>
    </div>
  );
}

function MetricsPage({ cpuHistory, latencyHistory }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px', padding: '24px' }}>
        <div style={{ color: '#888', fontSize: '11px', marginBottom: '20px', textTransform: 'uppercase', letterSpacing: '1px' }}>CPU Usage Over Time (%)</div>
        {cpuHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={cpuHistory}>
              <XAxis dataKey="time" tick={{ fill: '#333', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis domain={[0, 100]} tick={{ fill: '#333', fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: '8px', color: '#fff', fontSize: '12px' }} />
              {Object.keys(cpuHistory[0] || {}).filter(k => k !== 'time').map((nodeId, i) => (
                <Line key={nodeId} type="monotone" dataKey={nodeId} stroke={NODE_COLORS[i % NODE_COLORS.length]}
                  strokeWidth={2} dot={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : <div style={{ color: '#222', fontSize: '12px', textAlign: 'center', paddingTop: '80px' }}>Waiting for data...</div>}
      </div>

      <div style={{ background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px', padding: '24px' }}>
        <div style={{ color: '#888', fontSize: '11px', marginBottom: '20px', textTransform: 'uppercase', letterSpacing: '1px' }}>Inference Latency Over Time (ms)</div>
        {latencyHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={latencyHistory}>
              <XAxis dataKey="time" tick={{ fill: '#333', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#333', fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: '8px', color: '#fff', fontSize: '12px' }} />
              {Object.keys(latencyHistory[0] || {}).filter(k => k !== 'time').map((nodeId, i) => (
                <Line key={nodeId} type="monotone" dataKey={nodeId} stroke={NODE_COLORS[i % NODE_COLORS.length]}
                  strokeWidth={2} dot={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : <div style={{ color: '#222', fontSize: '12px', textAlign: 'center', paddingTop: '80px' }}>Waiting for data...</div>}
      </div>
    </div>
  );
}

function JobsPage({ jobs }) {
  const statusColor = { queued: '#f59e0b', running: '#6366f1', completed: '#10b981' };
  const statusIcon = { queued: '⏳', running: '⚡', completed: '✅' };
  const sorted = [...jobs].sort((a, b) => (b.submitted_at || 0) - (a.submitted_at || 0)).slice(0, 50);

  return (
    <div style={{ background: '#0c0c0f', border: '1px solid #1f1f2e', borderRadius: '12px', padding: '24px' }}>
      <div style={{ color: '#d8d8d8', fontSize: '15px', marginBottom: '20px', textTransform: 'uppercase', letterSpacing: '1px' }}>
        All Jobs ({jobs.length})
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr', gap: '12px', padding: '8px 12px', marginBottom: '8px' }}>
        {['Job ID', 'Type', 'Status', 'Node', 'Duration'].map(h => (
          <div key={h} style={{ color: '#f3f3f3', fontSize: '14px', textTransform: 'uppercase', letterSpacing: '1px' }}>{h}</div>
        ))}
      </div>
      {sorted.map(job => (
        <div key={job.job_id} style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr',
          gap: '12px', padding: '10px 12px', borderRadius: '8px',
          marginBottom: '4px', background: '#111118', fontSize: '12px'
        }}>
          <span style={{ color: '#888', fontFamily: 'monospace' }}>{job.job_id}</span>
          <span style={{ color: '#555' }}>{job.job_type}</span>
          <span style={{ color: statusColor[job.status] }}>{statusIcon[job.status]} {job.status}</span>
          <span style={{ color: '#555' }}>{job.assigned_node || '—'}</span>
          <span style={{ color: '#333' }}>
            {job.completed_at && job.started_at
              ? `${(job.completed_at - job.started_at).toFixed(1)}s`
              : job.started_at ? 'running...' : '—'}
          </span>
        </div>
      ))}
      {jobs.length === 0 && <div style={{ color: '#888', fontSize: '12px' }}>No jobs yet — submit one above</div>}
    </div>
  );
}

function NodesPage({ nodes, onKill, onRestart, onRemove }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '14px' }}>
      {nodes.length === 0
        ? <div style={{ color: '#222', fontSize: '12px' }}>No nodes registered yet</div>
        : nodes.map((node) => (
          <NodeCard key={node.node_id} node={node} onKill={onKill} onRestart={onRestart} onRemove={onRemove} />
        ))
      }
    </div>
  );
}

// ============================================================
// MAIN APP (rendered after session is established)
// ============================================================
function FleetDashboard({ sessionId, onEndSession }) {
  const api = useCallback(() => makeApi(sessionId), [sessionId]);

  const [activePage, setActivePage] = useState('overview');
  const [nodes, setNodes] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [queueLength, setQueueLength] = useState(0);
  const [summary, setSummary] = useState({});
  const [logs, setLogs] = useState([]);
  const [cpuHistory, setCpuHistory] = useState([]);
  const [latencyHistory, setLatencyHistory] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState('');
  const [nodeCount, setNodeCount] = useState(0);
  const MAX_NODES = 6;

  const addLog = (message, color = '#555') => {
    const time = new Date().toLocaleTimeString();
    setLogs(prev => [...prev.slice(-50), { time, message, color }]);
  };

  const fetchData = useCallback(async () => {
    const client = api();
    try {
      const [nodesRes, jobsRes, queueRes, summaryRes] = await Promise.all([
        client.get(`${REGISTRY_URL}/nodes`),
        client.get(`${SCHEDULER_URL}/jobs`),
        client.get(`${SCHEDULER_URL}/queue/length`),
        client.get(`${REGISTRY_URL}/fleet/summary`)
      ]);

      const fetchedNodes = nodesRes.data.nodes || [];
      const fetchedJobs = jobsRes.data.jobs || [];

      setJobs(prev => {
        fetchedJobs.forEach(job => {
          const prevJob = prev.find(j => j.job_id === job.job_id);
          if (prevJob?.status === 'queued' && job.status === 'running')
            addLog(`⚡ Job ${job.job_id} → assigned to ${job.assigned_node}`, '#6366f1');
          if (prevJob?.status === 'running' && job.status === 'completed')
            addLog(`✅ Job ${job.job_id} completed on ${job.assigned_node}`, '#10b981');
        });
        return fetchedJobs;
      });

      setNodes(fetchedNodes);
      setNodeCount(fetchedNodes.length);
      setQueueLength(queueRes.data.jobs_waiting || 0);
      setSummary(summaryRes.data || {});
      setLastUpdated(new Date().toLocaleTimeString());

      const time = new Date().toLocaleTimeString();
      const cpuPoint = { time };
      const latencyPoint = { time };
      fetchedNodes.filter(n => n.status === 'healthy').forEach(n => {
        cpuPoint[n.node_id] = parseFloat(n.cpu?.toFixed(1));
        latencyPoint[n.node_id] = parseFloat(n.inference_latency_ms?.toFixed(1));
      });
      setCpuHistory(prev => [...prev.slice(-MAX_HISTORY), cpuPoint]);
      setLatencyHistory(prev => [...prev.slice(-MAX_HISTORY), latencyPoint]);

    } catch (err) {
      if (err.response?.status === 403) {
        addLog('Session expired — please start a new session', '#f43f5e');
        onEndSession();
      }
    }
  }, [api, onEndSession]);

  // Data polling
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Session keepalive
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        await axios.post(
          `${SESSION_URL}/sessions/${sessionId}/heartbeat`,
          {},
          { headers: { 'x-session-token': sessionId } }
        );
      } catch {
        // session expired — handled by fetchData 403
      }
    }, SESSION_HEARTBEAT_INTERVAL);
    return () => clearInterval(interval);
  }, [sessionId]);

  const handleEndSession = async () => {
    try {
      await axios.post(
        `${SESSION_URL}/sessions/${sessionId}/end`,
        {},
        { headers: { 'x-session-token': sessionId } }
      );
    } catch { /* ignore */ }
    sessionStorage.removeItem('fleetos_session_id');
    onEndSession();
  };

  const handleAddNode = async () => {
    if (nodeCount >= MAX_NODES) {
      addLog(`Maximum ${MAX_NODES} nodes reached — kill one first`, '#f43f5e');
      return;
    }
    setLoading('adding');
    try {
      const res = await api().post(`${MANAGER_URL}/nodes/add`);
      if (res.data.error) {
        addLog(`Failed to add node: ${res.data.error}`, '#f43f5e');
      } else {
        addLog(`✅ ${res.data.node_id} joined the fleet`, '#10b981');
      }
    } catch (err) {
      addLog(err.response?.data?.detail || 'Failed to add node', '#f43f5e');
    }
    setLoading('');
  };

  const handleKillNode = async (nodeId) => {
    try {
      await api().post(`${MANAGER_URL}/nodes/${nodeId}/kill`);
      addLog(`💀 ${nodeId} killed`, '#f43f5e');
      setTimeout(() => addLog(`🔍 Self-healer scanning ${nodeId} for orphaned jobs...`, '#f59e0b'), 5000);
    } catch {
      addLog(`Failed to kill ${nodeId}`, '#f43f5e');
    }
  };

  const handleRestartNode = async (nodeId) => {
    try {
      await api().post(`${MANAGER_URL}/nodes/${nodeId}/restart`);
      addLog(`🟢 ${nodeId} restarting...`, '#10b981');
    } catch {
      addLog(`Failed to restart ${nodeId}`, '#f43f5e');
    }
  };

  const handleRemoveNode = async (nodeId) => {
    try {
      await api().post(`${MANAGER_URL}/nodes/${nodeId}/remove`);
      addLog(`🗑 ${nodeId} removed — slot freed`, '#a78bfa');
    } catch {
      addLog(`Failed to remove ${nodeId}`, '#f43f5e');
    }
  };

  const handleClearDead = async () => {
    try {
      await api().post(`${REGISTRY_URL}/fleet/clear-dead`);
      addLog('🧹 Cleared all dead nodes from registry', '#a78bfa');
    } catch {
      addLog('Failed to clear dead nodes', '#f43f5e');
    }
  };

  const handleSubmitJob = async (priority = 1) => {
    try {
      const res = await api().post(`${SCHEDULER_URL}/jobs/submit`, {
        job_type: 'inference', priority, payload: {}
      });
      addLog(
        priority >= 3
          ? `🚨 Urgent job ${res.data.job_id} → front of queue`
          : `⚡ Job ${res.data.job_id} queued`,
        priority >= 3 ? '#f59e0b' : '#6366f1'
      );
    } catch {
      addLog('Failed to submit job', '#f43f5e');
    }
  };

  const pages = { overview: OverviewPage, nodes: NodesPage, jobs: JobsPage, metrics: MetricsPage };
  const PageComponent = pages[activePage];

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#080810', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }}>
      <Sidebar active={activePage} setActive={setActivePage} onEndSession={handleEndSession} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{
          height: '60px', borderBottom: '1px solid #1f1f2e', display: 'flex',
          alignItems: 'center', justifyContent: 'space-between', padding: '0 24px',
          background: '#0c0c0f', flexShrink: 0
        }}>
          <div style={{ color: '#333', fontSize: '11px', fontFamily: 'monospace' }}>
            session: {sessionId.slice(0, 8)}... &nbsp;|&nbsp; updated {lastUpdated} &nbsp;|&nbsp;
            <span style={{ color: nodeCount >= MAX_NODES ? '#f43f5e' : '#444' }}>
              nodes: {nodeCount}/{MAX_NODES}
            </span>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button onClick={handleAddNode} disabled={loading === 'adding' || nodeCount >= MAX_NODES} style={{
              background: '#0d2818', border: '1px solid #10b98133', color: nodeCount >= MAX_NODES ? '#333' : '#10b981',
              borderRadius: '7px', padding: '7px 16px', fontSize: '12px', cursor: nodeCount >= MAX_NODES ? 'not-allowed' : 'pointer'
            }}>
              {loading === 'adding' ? 'Starting...' : '+ Add Node'}
            </button>
            <button onClick={() => handleSubmitJob(1)} style={{
              background: '#0d0d2a', border: '1px solid #6366f133', color: '#6366f1',
              borderRadius: '7px', padding: '7px 16px', fontSize: '12px', cursor: 'pointer'
            }}>⚡ Submit Job</button>
            <button onClick={() => handleSubmitJob(3)} style={{
              background: '#1a1208', border: '1px solid #f59e0b33', color: '#f59e0b',
              borderRadius: '7px', padding: '7px 16px', fontSize: '12px', cursor: 'pointer'
            }}>🚨 Urgent</button>
            <button onClick={handleClearDead} style={{
              background: '#1a0a2a', border: '1px solid #a78bfa33', color: '#a78bfa',
              borderRadius: '7px', padding: '7px 16px', fontSize: '12px', cursor: 'pointer'
            }}>🧹 Clear Dead</button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
          <PageComponent
            summary={summary}
            queueLength={queueLength}
            logs={logs}
            nodes={nodes}
            jobs={jobs}
            onKill={handleKillNode}
            onRestart={handleRestartNode}
            onRemove={handleRemoveNode}
            cpuHistory={cpuHistory}
            latencyHistory={latencyHistory}
            maxNodes={MAX_NODES}
          />
        </div>
      </div>
    </div>
  );
}

// ============================================================
// ROOT — session gate or dashboard
// ============================================================
export default function App() {
  const [sessionId, setSessionId] = useState(() => {
    return sessionStorage.getItem('fleetos_session_id') || null;
  });

  const handleSessionStart = (id) => setSessionId(id);
  const handleEndSession = () => setSessionId(null);

  if (!sessionId) {
    return <SessionGate onSessionStart={handleSessionStart} />;
  }

  return <FleetDashboard sessionId={sessionId} onEndSession={handleEndSession} />;
}
