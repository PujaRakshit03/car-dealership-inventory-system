import React, { useCallback, useEffect, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const TOKEN_KEY = "dealership_access_token";

async function request(path, { token, ...options } = {}) {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(", ")
      : detail || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function AuthPanel({ onLogin, onMessage }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    onMessage("");
    try {
      if (mode === "register") {
        await request("/auth/register", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        setMode("login");
        onMessage("Account created. Sign in to continue.");
      } else {
        const result = await request("/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        await onLogin(result.access_token);
      }
    } catch (error) {
      onMessage(error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-panel panel">
      <div className="auth-tabs" role="tablist" aria-label="Account">
        <button
          className={mode === "login" ? "tab active" : "tab"}
          onClick={() => setMode("login")}
          type="button"
        >
          Sign in
        </button>
        <button
          className={mode === "register" ? "tab active" : "tab"}
          onClick={() => setMode("register")}
          type="button"
        >
          Create account
        </button>
      </div>
      <h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2>
      <form onSubmit={submit} className="form-stack">
        <label>
          Username
          <input
            autoComplete="username"
            maxLength={64}
            onChange={(event) => setUsername(event.target.value)}
            required
            value={username}
          />
        </label>
        <label>
          Password
          <input
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={8}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        <button className="button primary" disabled={busy} type="submit">
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Register"}
        </button>
      </form>
    </section>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  const [vehicles, setVehicles] = useState([]);
  const [filters, setFilters] = useState({ make: "", model: "", min_price: "", max_price: "" });
  const [searchFilters, setSearchFilters] = useState(filters);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("success");
  const [busyVehicle, setBusyVehicle] = useState(null);
  const [restockAmounts, setRestockAmounts] = useState({});

  const showMessage = useCallback((text, type = "success") => {
    setMessage(text);
    setMessageType(type);
  }, []);

  const handleUnauthorized = useCallback(
    (error) => {
      if (error.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
        showMessage("Your session expired or is no longer valid. Please sign in again.", "error");
        return true;
      }
      return false;
    },
    [showMessage],
  );

  const loadVehicles = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(searchFilters).forEach(([key, value]) => {
        if (value !== "") params.set(key, value);
      });
      const query = params.size ? `?${params.toString()}` : "";
      setVehicles(await request(`/vehicles${query}`));
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      setLoading(false);
    }
  }, [searchFilters, showMessage]);

  const establishSession = useCallback(
    async (accessToken) => {
      localStorage.setItem(TOKEN_KEY, accessToken);
      setToken(accessToken);
      try {
        const profile = await request("/auth/me", { token: accessToken });
        setUser(profile);
        showMessage(`Signed in as ${profile.username}.`);
      } catch (error) {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
        showMessage(error.message, "error");
      }
    },
    [showMessage],
  );

  useEffect(() => {
    if (!token) {
      setUser(null);
      return;
    }
    let active = true;
    request("/auth/me", { token })
      .then((profile) => {
        if (active) setUser(profile);
      })
      .catch((error) => {
        if (active) handleUnauthorized(error);
      });
    return () => {
      active = false;
    };
  }, [handleUnauthorized, token]);

  useEffect(() => {
    loadVehicles();
  }, [loadVehicles]);

  async function purchase(vehicle) {
    const quantity = Number(window.prompt(`How many ${vehicle.make} ${vehicle.model}?`, "1"));
    if (!Number.isInteger(quantity) || quantity < 1) {
      if (quantity !== 0 && !Number.isNaN(quantity)) showMessage("Enter a positive whole quantity.", "error");
      return;
    }
    setBusyVehicle(vehicle.id);
    try {
      const updated = await request(`/vehicles/${vehicle.id}/purchase`, {
        method: "POST",
        token,
        body: JSON.stringify({ quantity }),
      });
      showMessage(`Purchase successful. ${updated.quantity} remaining.`);
      await loadVehicles();
    } catch (error) {
      if (!handleUnauthorized(error)) showMessage(error.message, "error");
    } finally {
      setBusyVehicle(null);
    }
  }

  async function restock(vehicle) {
    const quantity = Number(restockAmounts[vehicle.id]);
    if (!Number.isInteger(quantity) || quantity < 1) {
      showMessage("Enter a positive whole quantity to restock.", "error");
      return;
    }
    setBusyVehicle(vehicle.id);
    try {
      await request(`/vehicles/${vehicle.id}/restock`, {
        method: "POST",
        token,
        body: JSON.stringify({ quantity }),
      });
      showMessage(`${vehicle.make} ${vehicle.model} restocked.`);
      setRestockAmounts((current) => ({ ...current, [vehicle.id]: "" }));
      await loadVehicles();
    } catch (error) {
      if (!handleUnauthorized(error)) showMessage(error.message, "error");
    } finally {
      setBusyVehicle(null);
    }
  }

  async function removeVehicle(vehicle) {
    if (!window.confirm(`Delete ${vehicle.year} ${vehicle.make} ${vehicle.model}?`)) return;
    setBusyVehicle(vehicle.id);
    try {
      await request(`/vehicles/${vehicle.id}`, { method: "DELETE", token });
      showMessage(`${vehicle.make} ${vehicle.model} deleted.`);
      await loadVehicles();
    } catch (error) {
      if (!handleUnauthorized(error)) showMessage(error.message, "error");
    } finally {
      setBusyVehicle(null);
    }
  }

  function signOut() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    showMessage("You have signed out.");
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="brand-mark">DI</span>
          <span>Dealer<span className="brand-light">Inventory</span></span>
        </a>
        <div className="account-area">
          {user ? (
            <>
              <span className="user-label">
                {user.username}
                {user.role === "admin" && <span className="role-badge">Admin</span>}
              </span>
              <button className="button quiet" onClick={signOut} type="button">Sign out</button>
            </>
          ) : (
            <span className="guest-label">Browse inventory · Sign in to purchase</span>
          )}
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">CAR DEALERSHIP</p>
          <h1>Find your next drive.</h1>
          <p className="hero-copy">Explore our available vehicles and find the right fit.</p>
        </div>
        <div className="hero-stat">
          <strong>{vehicles.length}</strong>
          <span>{vehicles.length === 1 ? "vehicle shown" : "vehicles shown"}</span>
        </div>
      </section>

      {message && (
        <div className={`notice ${messageType}`} role="status">
          <span>{message}</span>
          <button aria-label="Dismiss message" onClick={() => setMessage("")} type="button">×</button>
        </div>
      )}

      {!user && (
        <AuthPanel onLogin={establishSession} onMessage={showMessage} />
      )}

      <section className="inventory-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">OUR COLLECTION</p>
            <h2>Available vehicles</h2>
          </div>
          <button className="button outline" disabled={loading} onClick={loadVehicles} type="button">
            Refresh
          </button>
        </div>

        <form
          className="filters panel"
          onSubmit={(event) => {
            event.preventDefault();
            setSearchFilters(filters);
          }}
        >
          <label>
            Make
            <input
              onChange={(event) => setFilters({ ...filters, make: event.target.value })}
              placeholder="Any make"
              value={filters.make}
            />
          </label>
          <label>
            Model
            <input
              onChange={(event) => setFilters({ ...filters, model: event.target.value })}
              placeholder="Any model"
              value={filters.model}
            />
          </label>
          <label>
            Min price
            <input
              min="0"
              onChange={(event) => setFilters({ ...filters, min_price: event.target.value })}
              placeholder="$0"
              type="number"
              value={filters.min_price}
            />
          </label>
          <label>
            Max price
            <input
              min="0"
              onChange={(event) => setFilters({ ...filters, max_price: event.target.value })}
              placeholder="No limit"
              type="number"
              value={filters.max_price}
            />
          </label>
          <button className="button primary filter-button" type="submit">Search</button>
        </form>

        {loading ? (
          <div className="empty-state panel">Loading inventory…</div>
        ) : vehicles.length === 0 ? (
          <div className="empty-state panel">No vehicles match these filters.</div>
        ) : (
          <div className="vehicle-grid">
            {vehicles.map((vehicle) => (
              <article className="vehicle-card panel" key={vehicle.id}>
                <div className="vehicle-visual" aria-hidden="true">
                  <span>{vehicle.make.slice(0, 1)}{vehicle.model.slice(0, 1)}</span>
                  <small>{vehicle.year}</small>
                </div>
                <div className="vehicle-content">
                  <div className="vehicle-title-row">
                    <div>
                      <p className="vehicle-make">{vehicle.make}</p>
                      <h3>{vehicle.model}</h3>
                    </div>
                    <span className={vehicle.quantity > 0 ? "stock-pill" : "stock-pill sold-out"}>
                      {vehicle.quantity > 0 ? `${vehicle.quantity} available` : "Out of stock"}
                    </span>
                  </div>
                  <div className="vehicle-details">
                    <span>{vehicle.year}</span>
                    <strong>{new Intl.NumberFormat("en-IN", {
                      style: "currency",
                      currency: "INR",
                      maximumFractionDigits: 0,
                    }).format(vehicle.price)}</strong>
                  </div>
                  {user && (
                    <button
                      className="button primary full-width"
                      disabled={vehicle.quantity < 1 || busyVehicle === vehicle.id}
                      onClick={() => purchase(vehicle)}
                      type="button"
                    >
                      {busyVehicle === vehicle.id ? "Working…" : "Purchase"}
                    </button>
                  )}
                  {user?.role === "admin" && (
                    <div className="admin-actions">
                      <div className="restock-control">
                        <input
                          aria-label={`Restock quantity for ${vehicle.make} ${vehicle.model}`}
                          min="1"
                          onChange={(event) =>
                            setRestockAmounts({ ...restockAmounts, [vehicle.id]: event.target.value })
                          }
                          placeholder="Qty"
                          type="number"
                          value={restockAmounts[vehicle.id] || ""}
                        />
                        <button
                          className="button outline"
                          disabled={busyVehicle === vehicle.id}
                          onClick={() => restock(vehicle)}
                          type="button"
                        >
                          Restock
                        </button>
                      </div>
                      <button
                        className="button danger"
                        disabled={busyVehicle === vehicle.id}
                        onClick={() => removeVehicle(vehicle)}
                        type="button"
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <footer>Inventory is subject to availability. Secure account access powered by your dealership.</footer>
    </main>
  );
}

export default App;
