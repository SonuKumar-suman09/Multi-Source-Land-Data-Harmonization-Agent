import { Activity, ShieldCheck } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

const recordColors = ["#1d7a67", "#dc9b39", "#bf6250", "#8b4651"];

export default function DashboardCharts({ summary }) {
  const jobs = Object.entries(summary?.job_status_counts || {}).map(([name, value]) => ({
    name: name.replaceAll("_", " "), value,
  }));
  const records = [
    { name: "Valid", value: summary?.valid_record_count || 0 },
    { name: "Review", value: summary?.review_record_count || 0 },
    { name: "Conflicts", value: summary?.conflict_record_count || 0 },
    { name: "Invalid", value: summary?.invalid_record_count || 0 },
  ].map((item, index) => ({ ...item, color: recordColors[index] }));

  return (
    <section className="insight-grid">
      <article className="panel">
        <div className="panel-heading"><div><span className="panel-kicker">PROCESSING</span><h2>Dataset activity</h2></div><span className="panel-badge"><Activity size={13} /> All jobs</span></div>
        <div className="chart-wrap">{jobs.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={jobs} margin={{ top: 12, right: 8, bottom: 3, left: -17 }}><CartesianGrid stroke="#edf0ee" vertical={false} /><XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "#8a948e", fontSize: 11 }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "#8a948e", fontSize: 11 }} /><Tooltip cursor={{ fill: "#f5f7f6" }} contentStyle={{ border: "1px solid #e6eae7", borderRadius: 9, fontSize: 12 }} /><Bar dataKey="value" name="Datasets" fill="#267464" radius={[5, 5, 0, 0]} maxBarSize={36} /></BarChart></ResponsiveContainer> : <EmptyChart icon={Activity} title="No processing activity yet" subtitle="Upload a source file to start your first workflow." />}</div>
      </article>
      <article className="panel quality-panel">
        <div className="panel-heading"><div><span className="panel-kicker">RECORD QUALITY</span><h2>Review distribution</h2></div><span className="panel-badge">{summary?.average_quality_score == null ? "No score yet" : `${summary.average_quality_score.toFixed(1)} avg.`}</span></div>
        <div className="quality-chart">{summary?.harmonized_record_count ? <><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={records} dataKey="value" nameKey="name" innerRadius={55} outerRadius={77} paddingAngle={3} stroke="none">{records.map((entry) => <Cell key={entry.name} fill={entry.color} />)}</Pie><Tooltip contentStyle={{ border: "1px solid #e6eae7", borderRadius: 9, fontSize: 12 }} /></PieChart></ResponsiveContainer><div className="donut-center"><b>{summary.harmonized_record_count}</b><span>records</span></div></> : <EmptyChart icon={ShieldCheck} title="Quality appears after processing" subtitle="Harmonize an uploaded dataset to see record status." />}</div>
        <div className="legend-grid">{records.map((item) => <div key={item.name}><span style={{ background: item.color }} />{item.name}<b>{item.value}</b></div>)}</div>
      </article>
    </section>
  );
}

function EmptyChart({ icon: Icon, title, subtitle }) {
  return <div className="chart-empty"><span><Icon size={19} /></span><b>{title}</b><small>{subtitle}</small></div>;
}
