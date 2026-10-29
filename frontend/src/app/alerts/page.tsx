"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bell, Mail, Pause, Plus, Trash2 } from "lucide-react";
import { safeDistanceToNow } from "@/lib/dateUtils";
import { createAlert, deleteAlert, fetchAlertPreferences, fetchAlerts, updateAlert, updateAlertPreferences, type AlertRule } from "@/lib/api";

const eventTypes = [
  { value: "", label: "Any event type" }, { value: "conflict", label: "Conflict" },
  { value: "sanction", label: "Sanction" }, { value: "trade_policy", label: "Trade policy" },
  { value: "economic_data", label: "Economic data" }, { value: "energy_disruption", label: "Energy disruption" },
  { value: "election", label: "Election" }, { value: "regulation", label: "Regulation" },
];

function errorMessage(error: unknown) {
  if (typeof error === "object" && error !== null && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Something went wrong. Please try again.";
}

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const [isAuthed, setIsAuthed] = useState(false);
  const [ticker, setTicker] = useState("");
  const [eventType, setEventType] = useState("");
  const [threshold, setThreshold] = useState("");
  useEffect(() => { setIsAuthed(Boolean(localStorage.getItem("access_token"))); }, []);

  const alerts = useQuery({ queryKey: ["alerts"], queryFn: fetchAlerts, enabled: isAuthed });
  const preferences = useQuery({ queryKey: ["alert-preferences"], queryFn: fetchAlertPreferences, enabled: isAuthed });
  const create = useMutation({ mutationFn: createAlert, onSuccess: async () => { setTicker(""); setEventType(""); setThreshold(""); await queryClient.invalidateQueries({ queryKey: ["alerts"] }); } });
  const toggle = useMutation({ mutationFn: ({ id, active }: { id: string; active: boolean }) => updateAlert(id, { is_active: active }), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["alerts"] }) });
  const remove = useMutation({ mutationFn: deleteAlert, onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["alerts"] }) });
  const updatePreferences = useMutation({ mutationFn: updateAlertPreferences, onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["alert-preferences"] }) });

  return <div className="ga-shell">
    <section className="ga-hero"><span className="ga-eyebrow"><Bell size={15} /> YOUR SIGNALS</span><h1>Stay close to<br />what matters.</h1><p>Follow the assets and event types you care about. Create a rule once, then manage it from one calm place.</p></section>

    {!isAuthed ? <section className="ga-section ga-empty ga-locked"><Bell size={30} /><h2>Your alerts, in one place</h2><p>Sign in to create and manage personal alert rules. You can continue exploring the map and news without an account.</p><div className="ga-hero-actions"><Link href="/login" className="ga-button ga-button-primary">Sign in to set alerts <ArrowRight size={16} /></Link><Link href="/map" className="ga-button ga-light-button">Explore the map</Link></div></section>
    : <>
      <section className="ga-section" aria-labelledby="delivery-heading"><div className="ga-section-head"><div><span className="ga-eyebrow">01 / DELIVERY</span><h2 id="delivery-heading">How you hear from us</h2><p>Choose a delivery channel when it is available.</p></div></div>
        <div className="ga-panel ga-preferences">
          <div className="ga-preference-item"><span className="ga-preference-icon"><Mail size={21} /></span><div><strong>Email updates</strong><p>{preferences.data?.email_delivery_ready ? "Receive matching event alerts by email." : "Email notifications are temporarily unavailable."}</p></div><label className="ga-switch"><input type="checkbox" aria-label="Email updates" checked={preferences.data?.email_enabled ?? false} disabled={!preferences.data?.email_delivery_ready || updatePreferences.isPending} onChange={(event) => updatePreferences.mutate({ email_enabled: event.target.checked })} /><span /></label></div>
          <div className="ga-preference-item"><span className="ga-preference-icon"><Bell size={21} /></span><div><strong>Browser updates</strong><p>Browser notifications are not available yet.</p></div><span className="ga-soon">Coming soon</span></div>
          {updatePreferences.isError && <p className="ga-error">{errorMessage(updatePreferences.error)}</p>}
        </div>
      </section>

      <section className="ga-section" aria-labelledby="new-rule-heading"><div className="ga-section-head"><div><span className="ga-eyebrow">02 / NEW RULE</span><h2 id="new-rule-heading">Create a signal</h2><p>Choose an asset, an event type, or both. You can pause the rule at any time.</p></div></div>
        <form className="ga-panel ga-rule-form" onSubmit={(event) => { event.preventDefault(); create.mutate({ ticker: ticker.trim() || undefined, event_type: eventType || undefined, threshold: threshold.trim() ? Number(threshold) : undefined, is_active: true }); }}>
          <label>Asset ticker <span>Optional</span><input className="ga-input" value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} placeholder="e.g. XOM or BTC" /></label>
          <label>Event type <span>Optional</span><select className="ga-input" value={eventType} onChange={(event) => setEventType(event.target.value)}>{eventTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label>Minimum score <span>Optional</span><input className="ga-input" value={threshold} onChange={(event) => setThreshold(event.target.value)} placeholder="e.g. 0.6" type="number" min="0" max="1" step="0.1" /></label>
          <button type="submit" className="ga-button ga-button-primary" disabled={create.isPending || (!ticker.trim() && !eventType)}><Plus size={16} /> {create.isPending ? "Creating…" : "Create alert"}</button>
          {create.isError && <p className="ga-error">{errorMessage(create.error)}</p>}
        </form>
      </section>

      <section className="ga-section" aria-labelledby="my-rules-heading"><div className="ga-section-head"><div><span className="ga-eyebrow">03 / YOUR RULES</span><h2 id="my-rules-heading">Active watch</h2><p>Review, pause, or remove your saved rules.</p></div></div>
        {alerts.isLoading ? <div className="skeleton ga-panel" style={{ height: 130 }} /> : alerts.isError ? <div className="ga-empty"><h3>Couldn’t load your rules</h3><p>Try again in a moment.</p><button className="ga-button ga-button-primary mt-5" onClick={() => alerts.refetch()}>Retry</button></div> : alerts.data?.length ? <div className="ga-rule-list">{alerts.data.map((alert) => <AlertRow key={alert.id} alert={alert} onToggle={() => toggle.mutate({ id: alert.id, active: !alert.is_active })} onDelete={() => remove.mutate(alert.id)} />)}</div> : <div className="ga-empty"><Bell size={26} /><h3>No alert rules yet</h3><p>Create a rule above to start following an asset or event type.</p></div>}
      </section>
    </>}
  </div>;
}

function AlertRow({ alert, onToggle, onDelete }: { alert: AlertRule; onToggle: () => void; onDelete: () => void }) {
  return <div className="ga-panel ga-alert-row"><span className={`ga-alert-state ${alert.is_active ? "is-active" : ""}`}>{alert.is_active ? "Active" : "Paused"}</span><div><h3>{alert.ticker || alert.asset_name || "All assets"}</h3><p>{alert.event_type ? alert.event_type.replace(/_/g, " ") : "Any event type"}{alert.threshold !== undefined ? ` · score ≥ ${alert.threshold}` : ""} · Created {safeDistanceToNow(alert.created_at)}</p></div><div className="ga-alert-actions"><button onClick={onToggle} aria-label={alert.is_active ? "Pause alert" : "Resume alert"}><Pause size={15} />{alert.is_active ? "Pause" : "Resume"}</button><button onClick={onDelete} aria-label="Delete alert"><Trash2 size={15} />Delete</button></div></div>;
}
