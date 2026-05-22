import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";
import { AuthProvider } from "@/contexts/AuthContext";
import ProtectedRoute, { RoleRedirect } from "@/components/ProtectedRoute";

import Login from "@/pages/Login";
import AdminLayout from "@/components/layouts/AdminLayout";
import EmployeeLayout from "@/components/layouts/EmployeeLayout";

import AdminOverview from "@/pages/admin/Overview";
import AdminEmployees from "@/pages/admin/Employees";
import AdminAttendance from "@/pages/admin/Attendance";
import AdminLeave from "@/pages/admin/Leave";
import AdminWFH from "@/pages/admin/WFH";
import AdminAnnouncements from "@/pages/admin/Announcements";
import AdminReports from "@/pages/admin/Reports";
import AdminSettings from "@/pages/admin/Settings";
import AdminJobs from "@/pages/admin/Jobs";
import AdminOrgChart from "@/pages/admin/OrgChart";
import AdminCompanies from "@/pages/admin/Companies";
import AdminPayroll from "@/pages/admin/Payroll";

import EmployeeToday from "@/pages/employee/Today";
import MyLeave from "@/pages/employee/MyLeave";
import MyWFH from "@/pages/employee/MyWFH";
import Profile from "@/pages/employee/Profile";
import MyPayslips from "@/pages/employee/MyPayslips";

import Chat from "@/pages/Chat";
import Meetings from "@/pages/Meetings";

import CareersHome from "@/pages/careers/CareersHome";
import JobDetail from "@/pages/careers/JobDetail";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster position="top-right" richColors closeButton />
        <Routes>
          <Route path="/" element={<RoleRedirect />} />
          <Route path="/login" element={<Login />} />

          {/* Public careers */}
          <Route path="/careers" element={<CareersHome />} />
          <Route path="/careers/:id" element={<JobDetail />} />

          {/* Admin */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute allow="admin">
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<AdminOverview />} />
            <Route path="employees" element={<AdminEmployees />} />
            <Route path="org" element={<AdminOrgChart />} />
            <Route path="attendance" element={<AdminAttendance />} />
            <Route path="leave" element={<AdminLeave />} />
            <Route path="wfh" element={<AdminWFH />} />
            <Route path="meetings" element={<div className="p-6"><Meetings /></div>} />
            <Route path="chat" element={<Chat />} />
            <Route path="announcements" element={<AdminAnnouncements />} />
            <Route path="reports" element={<AdminReports />} />
            <Route path="payroll" element={<AdminPayroll />} />
            <Route path="jobs" element={<AdminJobs />} />
            <Route path="companies" element={<AdminCompanies />} />
            <Route path="settings" element={<AdminSettings />} />
          </Route>

          {/* Employee */}
          <Route
            path="/employee"
            element={
              <ProtectedRoute allow="employee">
                <EmployeeLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<EmployeeToday />} />
            <Route path="leave" element={<MyLeave />} />
            <Route path="wfh" element={<MyWFH />} />
            <Route path="payslips" element={<MyPayslips />} />
            <Route path="meetings" element={<Meetings />} />
            <Route path="chat" element={<Chat />} />
            <Route path="profile" element={<Profile />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
