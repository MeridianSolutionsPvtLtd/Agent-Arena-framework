import React from 'react';
import Skeleton from './Skeleton';

export default function SkeletonConversationItem() {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-transparent">
      <Skeleton variant="rounded" className="w-7 h-7 rounded-lg shrink-0" />
      <div className="flex-1 min-w-0 space-y-1.5">
        <Skeleton variant="text" className="h-3.5 w-3/4 rounded" />
        <Skeleton variant="text" className="h-2.5 w-1/2 rounded" />
      </div>
    </div>
  );
}
