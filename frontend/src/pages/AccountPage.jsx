import { useState } from "react";
import { CalendarDays, Check, KeyRound, Mail, Save, ShieldCheck, UserRound } from "lucide-react";
import { apiRequest } from "../services/api.js";

export default function AccountPage({ user, onUserUpdated }) {
  const [displayName, setDisplayName] = useState(user.display_name || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function saveProfile(event) {
    event.preventDefault();
    setBusy(true); setError(""); setSaved(false);
    try {
      const updated = await apiRequest("/api/v1/auth/me", {
        method: "PATCH",
        body: JSON.stringify({ display_name: displayName }),
      });
      onUserUpdated(updated);
      setDisplayName(updated.display_name || "");
      setSaved(true);
    } catch (problem) { setError(problem.message); }
    finally { setBusy(false); }
  }

  const joined = user.created_at ? new Intl.DateTimeFormat(undefined, { dateStyle: "long" }).format(new Date(user.created_at)) : "—";
  return <>
    <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> ACCOUNT SETTINGS</div><h1>Account center</h1><p>Update how your name appears in this workspace and review your account details.</p></div></div>
    <div className="account-layout">
      <form className="panel account-panel" onSubmit={saveProfile}>
        <div className="account-panel-heading"><span className="account-icon"><UserRound size={19} /></span><div><span className="panel-kicker">PROFILE</span><h2>Your name</h2><p>This name appears in your workspace greeting and account menu.</p></div></div>
        <label className="field-label" htmlFor="account-display-name">Display name<input id="account-display-name" className="text-input" value={displayName} onChange={(event) => { setDisplayName(event.target.value); setSaved(false); }} maxLength={120} minLength={2} placeholder="Enter your name" required /></label>
        {error && <div className="inline-notice notice-error">Could not save your profile: {error}</div>}
        {saved && <div className="inline-notice notice-success"><Check size={15} /> Name saved to your account.</div>}
        <div className="account-actions"><span><ShieldCheck size={15} /> Changes are saved to your signed-in account.</span><button className="button button-primary" disabled={busy || displayName.trim() === (user.display_name || "")}>{busy ? "Saving…" : <><Save size={15} /> Save name</>}</button></div>
      </form>
      <section className="panel account-panel">
        <div className="account-panel-heading"><span className="account-icon account-icon-blue"><KeyRound size={18} /></span><div><span className="panel-kicker">ACCOUNT DETAILS</span><h2>Sign-in and access</h2><p>Your email and role identify this account.</p></div></div>
        <div className="account-details">
          <Detail icon={Mail} label="Sign-in email" value={user.email} />
          <Detail icon={ShieldCheck} label="Workspace role" value={(user.role || "analyst").replaceAll("_", " ")} />
          <Detail icon={CalendarDays} label="Member since" value={joined} />
          <Detail icon={KeyRound} label="Account status" value={user.is_active ? "Active" : "Inactive"} />
        </div>
        <p className="account-readonly-note">For account safety, email and access role are read-only here.</p>
      </section>
    </div>
  </>;
}

function Detail({ icon: Icon, label, value }) {
  return <div className="account-detail"><span><Icon size={15} /></span><div><small>{label}</small><b>{value}</b></div></div>;
}
