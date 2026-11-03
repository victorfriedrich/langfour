"use client";

import VideoHome from '../components/home/VideoHome';
import ProtectedRoute from '../components/ProtectedRoute';

export default function VideosPage() {
  return <ProtectedRoute><VideoHome /></ProtectedRoute>;
}