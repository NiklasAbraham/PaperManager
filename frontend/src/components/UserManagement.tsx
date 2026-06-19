import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Mirror of the backend password policy (services/auth.validate_password_strength)
// so users get immediate feedback before the request is rejected server-side.
const PASSWORD_RULES: { test: (pw: string) => boolean; label: string }[] = [
  { test: (pw) => pw.length >= 8, label: "at least 8 characters" },
  { test: (pw) => /[a-z]/.test(pw), label: "a lowercase letter" },
  { test: (pw) => /[A-Z]/.test(pw), label: "an uppercase letter" },
  { test: (pw) => /[0-9]/.test(pw), label: "a digit" },
];

function passwordIssues(pw: string): string[] {
  return PASSWORD_RULES.filter((r) => !r.test(pw)).map((r) => r.label);
}

interface User {
  name: string;
  id: string;
  created_at: string;
  is_admin?: boolean;
  paper_count?: number;
  conversation_count?: number;
  note_count?: number;
  connection_count?: number;
}

const inputClass =
  "w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-500 focus:border-violet-500 disabled:bg-gray-50 disabled:text-gray-400";

function PasswordRequirements({ value }: { value: string }) {
  if (!value) {
    return (
      <p className="mt-1 text-xs text-gray-400">
        Must contain {PASSWORD_RULES.map((r) => r.label).join(", ")}.
      </p>
    );
  }
  return (
    <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
      {PASSWORD_RULES.map((r) => {
        const ok = r.test(value);
        return (
          <li
            key={r.label}
            className={`text-xs flex items-center gap-1 ${ok ? "text-green-600" : "text-gray-400"}`}
          >
            <span aria-hidden>{ok ? "✓" : "○"}</span>
            {r.label}
          </li>
        );
      })}
    </ul>
  );
}

/** A titled, bordered section used to group each admin action. */
function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl p-5">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      {children}
    </section>
  );
}

export default function UserManagement() {
  const { isAdmin, username } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Password update
  const [updateUsername, setUpdateUsername] = useState("");
  const [updatePassword, setUpdatePassword] = useState("");
  const [updating, setUpdating] = useState(false);

  // Delete
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deletingUser, setDeletingUser] = useState<string | null>(null);

  // Merge users
  const [mergeUserA, setMergeUserA] = useState("");
  const [mergeUserB, setMergeUserB] = useState("");
  const [keepUser, setKeepUser] = useState("");
  const [passwordSourceUser, setPasswordSourceUser] = useState("");
  const [merging, setMerging] = useState(false);

  const canManageTeammates = isAdmin && username?.toLowerCase() === "niklas";

  const fetchUsers = async () => {
    try {
      const response = await fetch(`${BASE_URL}/auth/admin/users`, {
        credentials: "include",
      });
      if (response.ok) {
        const data = await response.json();
        setUsers(data);
      }
    } catch (err) {
      console.error("Failed to fetch users:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchUsers();
    }
  }, [isAdmin]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    const issues = passwordIssues(newPassword);
    if (issues.length) {
      setError(`Password must contain ${issues.join(", ")}.`);
      return;
    }

    setCreating(true);
    try {
      const response = await fetch(`${BASE_URL}/auth/admin/create-user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username: newUsername, password: newPassword }),
      });

      if (response.ok) {
        setSuccess(`User "${newUsername}" created successfully`);
        setNewUsername("");
        setNewPassword("");
        fetchUsers();
      } else {
        const data = await response.json();
        setError(data.detail || "Failed to create user");
      }
    } catch (err) {
      setError("Network error");
    } finally {
      setCreating(false);
    }
  };

  const handleUpdatePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    const issues = passwordIssues(updatePassword);
    if (issues.length) {
      setError(`Password must contain ${issues.join(", ")}.`);
      return;
    }

    setUpdating(true);
    try {
      const response = await fetch(`${BASE_URL}/auth/admin/update-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username: updateUsername, new_password: updatePassword }),
      });

      if (response.ok) {
        setSuccess(`Password updated for "${updateUsername}"`);
        setUpdateUsername("");
        setUpdatePassword("");
      } else {
        const data = await response.json();
        setError(data.detail || "Failed to update password");
      }
    } catch (err) {
      setError("Network error");
    } finally {
      setUpdating(false);
    }
  };

  const handleDeleteUser = async (username: string) => {
    setError("");
    setSuccess("");
    setDeletingUser(username);
    try {
      const response = await fetch(`${BASE_URL}/auth/admin/users/${encodeURIComponent(username)}`, {
        method: "DELETE",
        credentials: "include",
      });

      if (response.ok) {
        setSuccess(`User "${username}" deleted`);
        fetchUsers();
      } else {
        const text = await response.text();
        try {
          const data = JSON.parse(text);
          setError(data.detail || "Failed to delete user");
        } catch {
          setError(text || "Failed to delete user");
        }
      }
    } catch (err) {
      setError("Network error");
    } finally {
      setDeletingUser(null);
      setConfirmDelete(null);
    }
  };

  const getConnectionCount = (user: User) =>
    (user.paper_count || 0) + (user.conversation_count || 0) + (user.note_count || 0);

  useEffect(() => {
    if (!mergeUserA || !mergeUserB || mergeUserA === mergeUserB) {
      return;
    }
    const userA = users.find((u) => u.name === mergeUserA);
    const userB = users.find((u) => u.name === mergeUserB);
    if (!userA || !userB) {
      return;
    }
    const autoKeep = getConnectionCount(userA) >= getConnectionCount(userB) ? userA.name : userB.name;
    setKeepUser(autoKeep);
    setPasswordSourceUser(autoKeep);
  }, [mergeUserA, mergeUserB, users]);

  const handleMergeUsers = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (!mergeUserA || !mergeUserB || mergeUserA === mergeUserB) {
      setError("Please select two different users to merge");
      return;
    }

    if (!keepUser || !passwordSourceUser) {
      setError("Please choose which user to keep and which password to keep");
      return;
    }

    setMerging(true);
    try {
      const response = await fetch(`${BASE_URL}/auth/admin/merge-users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          user_a: mergeUserA,
          user_b: mergeUserB,
          keep_user: keepUser,
          password_source_user: passwordSourceUser,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setSuccess(
          `Merged users successfully. Kept "${data.kept_user}", removed "${data.removed_user}", moved ${data.moved_papers} papers, ${data.moved_conversations} conversations, and ${data.moved_notes} notes.`
        );
        setMergeUserA("");
        setMergeUserB("");
        setKeepUser("");
        setPasswordSourceUser("");
        fetchUsers();
      } else {
        const text = await response.text();
        try {
          const data = JSON.parse(text);
          setError(data.detail || `Failed to merge users (${response.status})`);
        } catch {
          setError(text || `Failed to merge users (${response.status})`);
        }
      }
    } catch {
      setError("Network error while calling merge endpoint");
    } finally {
      setMerging(false);
    }
  };

  if (!isAdmin) {
    return null;
  }

  if (loading) {
    return <div className="px-5 py-4 text-sm text-gray-500">Loading users...</div>;
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-900">User Management</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Create teammates, merge duplicate users, and manage credentials.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">{error}</div>
      )}
      {success && (
        <div className="p-3 bg-green-50 border border-green-200 text-green-700 rounded-lg text-sm">{success}</div>
      )}

      {!canManageTeammates && (
        <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg text-sm">
          Teammate creation and user merge are restricted to admin user "niklas".
        </div>
      )}

      <Section
        title="Create New Teammate"
        description="Available only for admin user niklas."
      >
        <form onSubmit={handleCreateUser} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-start">
            <input
              type="text"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              required
              disabled={!canManageTeammates}
              className={inputClass}
              placeholder="Username"
            />
            <div>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                disabled={!canManageTeammates}
                className={inputClass}
                placeholder="Password"
              />
              <PasswordRequirements value={newPassword} />
            </div>
            <button
              type="submit"
              disabled={creating || !canManageTeammates}
              className="px-4 py-2 text-sm font-medium bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors h-[38px]"
            >
              {creating ? "Creating..." : "Create Teammate"}
            </button>
          </div>
        </form>
      </Section>

      <Section
        title="Merge Two Users"
        description="Defaults to keeping the user with more connections. You can override keep-user and password source."
      >
        <form onSubmit={handleMergeUsers} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <select
              value={mergeUserA}
              onChange={(e) => setMergeUserA(e.target.value)}
              required
              disabled={!canManageTeammates}
              className={inputClass}
            >
              <option value="">User A</option>
              {users.map((user) => (
                <option key={`a-${user.name}`} value={user.name}>
                  {user.name} ({getConnectionCount(user)} connections)
                </option>
              ))}
            </select>
            <select
              value={mergeUserB}
              onChange={(e) => setMergeUserB(e.target.value)}
              required
              disabled={!canManageTeammates}
              className={inputClass}
            >
              <option value="">User B</option>
              {users.map((user) => (
                <option key={`b-${user.name}`} value={user.name}>
                  {user.name} ({getConnectionCount(user)} connections)
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <select
              value={keepUser}
              onChange={(e) => setKeepUser(e.target.value)}
              required
              disabled={!canManageTeammates || !mergeUserA || !mergeUserB || mergeUserA === mergeUserB}
              className={inputClass}
            >
              <option value="">Keep This User</option>
              {[mergeUserA, mergeUserB].filter(Boolean).map((name) => (
                <option key={`keep-${name}`} value={name}>{name}</option>
              ))}
            </select>
            <select
              value={passwordSourceUser}
              onChange={(e) => setPasswordSourceUser(e.target.value)}
              required
              disabled={!canManageTeammates || !mergeUserA || !mergeUserB || mergeUserA === mergeUserB}
              className={inputClass}
            >
              <option value="">Keep Password From</option>
              {[mergeUserA, mergeUserB].filter(Boolean).map((name) => (
                <option key={`pwd-${name}`} value={name}>{name}</option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={merging || !canManageTeammates}
            className="px-4 py-2 text-sm font-medium bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-colors"
          >
            {merging ? "Merging..." : "Merge Users"}
          </button>
        </form>
      </Section>

      <Section
        title="Update User Password"
        description="Change the password for an existing user."
      >
        <form onSubmit={handleUpdatePassword} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-start">
            <select
              value={updateUsername}
              onChange={(e) => setUpdateUsername(e.target.value)}
              required
              className={inputClass}
            >
              <option value="">Select user</option>
              {users.map((user) => (
                <option key={user.name} value={user.name}>
                  {user.name}
                </option>
              ))}
            </select>
            <div>
              <input
                type="password"
                value={updatePassword}
                onChange={(e) => setUpdatePassword(e.target.value)}
                required
                className={inputClass}
                placeholder="New password"
              />
              <PasswordRequirements value={updatePassword} />
            </div>
            <button
              type="submit"
              disabled={updating}
              className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors h-[38px]"
            >
              {updating ? "Updating..." : "Update Password"}
            </button>
          </div>
        </form>
      </Section>

      <Section
        title={`Existing Users (${users.length})`}
        description="All registered accounts and their activity."
      >
        <div className="border border-gray-200 rounded-lg overflow-hidden overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Username</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Role</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Papers</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Conversations</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Notes</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Connections</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {users.map((user) => (
                <tr key={user.name} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{user.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {user.is_admin ? (
                      <span className="px-2 py-1 text-xs font-semibold text-violet-700 bg-violet-100 rounded">Admin</span>
                    ) : (
                      <span className="text-gray-400">User</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">{user.paper_count || 0}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{user.conversation_count || 0}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{user.note_count || 0}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{getConnectionCount(user)}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {user.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {confirmDelete === user.name ? (
                      <div className="flex gap-2 justify-end">
                        <button
                          type="button"
                          onClick={() => handleDeleteUser(user.name)}
                          disabled={deletingUser === user.name}
                          className="px-2 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700"
                        >
                          {deletingUser === user.name ? "Deleting..." : "Confirm"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(null)}
                          disabled={deletingUser === user.name}
                          className="px-2 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(user.name)}
                        disabled={user.name === username}
                        className="px-3 py-1 text-xs text-red-600 hover:text-red-800 disabled:text-gray-400 disabled:cursor-not-allowed"
                      >
                        {user.name === username ? "Current user" : "Delete"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
