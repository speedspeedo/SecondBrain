"use client";

import { useSearchParams } from 'next/navigation';

import { ActionsBar } from "./components/ActionsBar";
import { ChatHeader } from "./components/ChatHeader";
import { ChatDialog } from "./components/Dialog";

const SelectedChatPage = (): JSX.Element => {
  // http://147.182.142.200:3000/share-brain?brainId={brain_id}&userId={current_user.id}
  // ?brainId=235252&userId=246262
  const searchParams = useSearchParams();
 
  const brainId = searchParams?.get('brainId') ?? "";
  const userId = searchParams?.get('userId') ?? "";
  const brainName = searchParams?.get('brainName') ?? "";


  return (
    <div className="flex flex-col w-full pt-10" data-testid="chat-page">
      <div className="flex flex-col flex-1 items-center w-full h-full min-h-[94.9vh]">
        <ChatHeader brainName={brainName} />
        <div className="flex-1 flex flex-col mt-1 w-full rounded-sm shadow-md dark:shadow-primary/25 hover:shadow-xl transition-shadow overflow-hidden bg-white dark:bg-black border border-black/10 dark:border-white/25 p-3 max-h-[110vh]">
          <div className="flex flex-col flex-1 overflow-hidden">
            <ChatDialog />
          </div>
          <ActionsBar userId={userId}  brainId={brainId} />
        </div>
      </div>
    </div>
  );
};

export default SelectedChatPage;
