import React, { useState, useEffect, createContext, useContext, useCallback, useRef } from 'react';

// Tailwind CSS (CDN - assumed to be available)
// HTMLファイルに以下を追加してください:
// <script src="https://cdn.tailwindcss.com"></script>

// Lucide React for icons (assumed to be available via CDN or local setup)
// HTMLファイルに以下を追加してください (type="module"が重要):
// <script type="module">
//   import { Camera, Trash, Edit, Search, ArrowLeft, ArrowRight, Save, XCircle, CheckCircle } from 'https://unpkg.com/lucide-react@0.395.0/dist/lucide-react.js';
//   window.LucideReact = { Camera, Trash, Edit, Search, ArrowLeft, ArrowRight, Save, XCircle, CheckCircle };
// </script>

const LucideReact = window.LucideReact; // グローバルスコープからLucideReactコンポーネントにアクセス

// --- カラーテーマ (Kivyアプリから) ---
const COLORS = {
  BACKGROUND: '#F7FAFC',
  TEXT: '#2D3748',
  SUBTEXT: '#718096',
  PRIMARY: '#3182CE',
  SUCCESS: '#38A169',
  DANGER: '#E53E3E',
  CARD_BG: '#FFFFFF',
  INPUT_BG: '#EDF2F7',
  DARK_BUTTON: '#A0AEC0',
};

// Flask APIのベースURL
// FlaskサーバーがPythonAnywhereで稼働しているURLに更新します
const API_BASE_URL = 'http://saigai.pythonanywhere.com'; // PythonAnywhereのあなたのURLに置き換えてください

// グローバル状態管理のためのAppコンテキスト
const AppContext = createContext();

// --- 再利用可能なUIコンポーネント ---

const Card = ({ children, className = '' }) => (
  <div className={`bg-white rounded-lg shadow-md p-4 space-y-2 ${className}`}>
    {children}
  </div>
);

const SectionHeader = ({ children, className = '' }) => (
  <h2 className={`text-xl font-bold text-[${COLORS.PRIMARY}] border-b-2 border-[${COLORS.PRIMARY}] pb-2 mb-4 ${className}`}>
    {children}
  </h2>
);

const Button = ({ children, onClick, color = COLORS.PRIMARY, className = '', icon: Icon, disabled = false }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className={`flex items-center justify-center px-4 py-2 rounded-md font-semibold text-white shadow-sm transition-colors duration-200
      ${disabled ? `bg-[${COLORS.DARK_BUTTON}] cursor-not-allowed opacity-70` : `bg-[${color}] hover:bg-opacity-80`}
      ${className}`}
    style={{ backgroundColor: color }}
  >
    {Icon && <Icon size={20} className="mr-2" />}
    {children}
  </button>
);

const TextInput = ({ label, type = 'text', value, onChange, placeholder, multiline = false, readOnly = false, password = false, className = '' }) => (
  <div className="flex flex-col mb-4">
    {label && <label className={`block text-sm font-medium text-[${COLORS.SUBTEXT}] mb-1`}>{label}</label>}
    {multiline ? (
      <textarea
        className={`mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 bg-[${COLORS.INPUT_BG}] focus:ring-blue-500 focus:border-blue-500 ${className}`}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        readOnly={readOnly}
        rows={multiline ? 4 : 1}
      ></textarea>
    ) : (
      <input
        type={password ? 'password' : type}
        className={`mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 bg-[${COLORS.INPUT_BG}] focus:ring-blue-500 focus:border-blue-500 ${className}`}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        readOnly={readOnly}
      />
    )}
  </div>
);

const SwitchInput = ({ label, checked, onChange, className = '' }) => (
  <div className="flex items-center justify-between mb-4">
    <label className={`block text-sm font-medium text-[${COLORS.SUBTEXT}] mr-2`}>{label}</label>
    <div
      onClick={onChange}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out
        ${checked ? `bg-[${COLORS.PRIMARY}]` : 'bg-gray-200'} focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${className}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out
          ${checked ? 'translate-x-5' : 'translate-x-0'}`}
      ></span>
    </div>
  </div>
);

const StatusMessage = ({ message, type }) => {
  let color = COLORS.SUBTEXT;
  if (type === 'success') color = COLORS.SUCCESS;
  if (type === 'error') color = COLORS.DANGER;
  if (type === 'loading') color = COLORS.PRIMARY;

  return (
    <p className="text-center text-sm mt-2" style={{ color }}>
      {message}
    </p>
  );
};

const Modal = ({ title, message, onConfirm, onCancel, show }) => {
  if (!show) return null;
  return (
    <div className="fixed inset-0 bg-gray-600 bg-opacity-75 flex items-center justify-center z-50">
      <div className="bg-white p-6 rounded-lg shadow-xl max-w-sm w-full mx-4">
        <h3 className="text-lg font-bold text-gray-900 mb-4">{title}</h3>
        <p className="text-sm text-gray-700 mb-6">{message}</p>
        <div className="flex justify-end space-x-3">
          {onCancel && (
            <Button onClick={onCancel} color={COLORS.DARK_BUTTON}>
              キャンセル
            </Button>
          )}
          {onConfirm && (
            <Button onClick={onConfirm} color={COLORS.DANGER}>
              {onCancel ? '削除' : 'OK'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};


// --- スクリーン (各画面) ---

const MenuScreen = ({ navigate }) => {
  const { clearUserData } = useContext(AppContext);
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-100 p-8">
      <h1 className={`text-5xl font-extrabold text-[${COLORS.PRIMARY}] mb-12 text-center`}>
        医療情報管理アプリ
      </h1>
      <div className="flex flex-col space-y-6 w-full max-w-md">
        <Button onClick={() => { clearUserData(); navigate('step1'); }} color={COLORS.PRIMARY}>
          新規利用者登録
        </Button>
        <Button onClick={() => alert('アプリを終了します。')} color={COLORS.DARK_BUTTON}>
          アプリを終了
        </Button>
      </div>
    </div>
  );
};

const UserListScreen = ({ navigate }) => {
  const [users, setUsers] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [status, setStatus] = useState({ message: '', type: '' });
  const { setSelectedUserId } = useContext(AppContext);

  const fetchUsers = useCallback(async (query = '') => {
    setStatus({ message: 'ユーザーを読み込み中...', type: 'loading' });
    try {
      const url = query ? `${API_BASE_URL}/search_users?q=${query}` : `${API_BASE_URL}/get_users`;
      const response = await fetch(url, { signal: AbortSignal.timeout(3000) });
      const data = await response.json();

      if (response.ok) {
        setUsers(data);
        if (data.length === 0) {
          setStatus({ message: query ? `「${query}」に一致するユーザーはいません。` : '登録されているユーザーはいません。', type: '' });
        } else {
          setStatus({ message: '', type: '' });
        }
      } else {
        setStatus({ message: `APIエラー: ${data.message || '不明なエラー'}`, type: 'error' });
      }
    } catch (error) {
      setStatus({ message: `通信エラー: サーバーに接続できません。Flaskサーバーが起動していることを確認してください。(${error.message})`, type: 'error' });
      setUsers([]);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSearch = () => {
    // 再帰呼び出しを削除し、fetchUsersを直接呼び出すように変更しました
    fetchUsers(searchTerm); 
  };

  const handleReset = () => {
    setSearchTerm('');
    fetchUsers();
  };

  const viewUserDetails = (userId) => {
    setSelectedUserId(userId);
    navigate('detail');
  };

  return (
    <div className="flex flex-col h-screen bg-gray-100 p-6">
      <h1 className={`text-3xl font-bold text-[${COLORS.PRIMARY}] mb-6 text-center`}>登録者一覧</h1>

      <div className="flex space-x-2 mb-4">
        <TextInput
          placeholder="名前で検索..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="flex-grow"
        />
        <Button onClick={handleSearch} icon={LucideReact.Search}>
          検索
        </Button>
        <Button onClick={handleReset} color={COLORS.DARK_BUTTON}>
          リセット
        </Button>
      </div>

      <div className="flex-grow overflow-y-auto rounded-lg shadow-md bg-white p-4">
        {users.length === 0 && status.type !== 'loading' ? (
          <p className="text-center text-gray-500">{status.message || '登録されているユーザーはいません。'}</p>
        ) : (
          <div className="space-y-2">
            {users.map((user) => (
              <button
                key={user.id}
                onClick={() => viewUserDetails(user.id)}
                className={`w-full text-left bg-[${COLORS.CARD_BG}] hover:bg-gray-50 text-[${COLORS.TEXT}] font-semibold py-3 px-4 rounded-md shadow-sm transition-colors duration-200`}
              >
                ID: {user.id} - 名前: {user.name}
              </button>
            ))}
          </div>
        )}
        {status.type === 'loading' && <StatusMessage message={status.message} type={status.type} />}
        {status.type === 'error' && <StatusMessage message={status.message} type={status.type} />}
      </div>

      <div className="mt-6">
        <Button onClick={() => navigate('menu')} color={COLORS.DARK_BUTTON} className="w-full">
          メニューに戻る
        </Button>
      </div>
    </div>
  );
};

const DetailScreen = ({ navigate }) => {
  const { selectedUserId, user_data, setUserData, clearUserData, setEditingUserId } = useContext(AppContext);
  const [status, setStatus] = useState({ message: '', type: '' });
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  const fetchUserDetails = useCallback(async () => {
    if (!selectedUserId) {
      setStatus({ message: 'ユーザーが選択されていません。', type: 'error' });
      return;
    }
    setStatus({ message: 'ユーザー詳細を読み込み中...', type: 'loading' });
    try {
      const response = await fetch(`${API_BASE_URL}/get_user/${selectedUserId}`, { signal: AbortSignal.timeout(3000) });
      const data = await response.json();

      if (response.ok) {
        setUserData(data);
        setStatus({ message: '', type: '' });
      } else {
        setStatus({ message: `APIエラー: ${data.message || '不明なエラー'}`, type: 'error' });
      }
    } catch (error) {
      setStatus({ message: `通信エラー: サーバーに接続できません。(${error.message})`, type: 'error' });
    }
  }, [selectedUserId, setUserData]);

  useEffect(() => {
    fetchUserDetails();
  }, [fetchUserDetails]);

  const handleEdit = () => {
    setEditingUserId(selectedUserId);
    navigate('step1');
  };

  const handleDeleteConfirm = () => {
    setShowDeleteModal(true);
  };

  const handleDelete = async () => {
    setShowDeleteModal(false);
    setStatus({ message: 'ユーザーを削除中...', type: 'loading' });
    try {
      const response = await fetch(`${API_BASE_URL}/delete_user/${selectedUserId}`, {
        method: 'DELETE',
        signal: AbortSignal.timeout(3000),
      });

      if (response.ok) {
        setStatus({ message: 'ユーザーが正常に削除されました。', type: 'success' });
        clearUserData(); // アプリ全体のユーザーデータをクリア
        navigate('user_list');
      } else {
        const data = await response.json();
        setStatus({ message: `削除エラー: ${data.message || '不明なエラー'}`, type: 'error' });
      }
    } catch (error) {
      setStatus({ message: `通信エラー: サーバーに接続できません。(${error.message})`, type: 'error' });
    }
  };

  const renderFieldValue = (fieldId, value) => {
    if (fieldId === 'photo_path') {
      // photo_path が 'data:image/' で始まる場合はbase64、そうでなければURLとして表示
      return value && typeof value === 'string' && (value.startsWith('data:image/') || value.startsWith('http://') || value.startsWith('https://')) ? (
        <img src={value} alt="顔写真" className="max-w-xs max-h-[150px] object-contain rounded-md" />
      ) : (
        <span>写真なし</span>
      );
    }
    if (['has_support', 'in_use'].includes(fieldId)) {
      return value === 1 ? 'はい' : 'いいえ';
    }
    return value || 'N/A';
  };


  const allFields = {
    "利用者基本情報": [
      ("名前", "name"), ("年齢", "age"), ("メールアドレス", "email_address"),
      ("電話番号", "phone"), ("性別", "gender"), ("血液型", "blood_type"), ("担当医師", "doctor")
    ],
    "顔写真": [("顔写真パス", "photo_path")],
    "緊急連絡先": [
      ("名前", "contact_name"), ("続柄", "contact_relation"), ("電話番号", "contact_phone")
    ],
    "持病・アレルギー・服用薬情報": [
      ("病名", "disease_name"), ("発症時期", "since_date"), ("病歴メモ", "disease_memo"),
      ("アレルギー名", "allergy_name"), ("アレルギーに関するメモ", "allergy_memo"),
      ("薬の名前", "med_name"), ("薬の服用量", "dosage"),
      ("服用スケジュール", "schedule"), ("薬に関するメモ", "med_memo")
    ],
    "医療的・日常的支援情報": [
      ("医療的支援内容", "support_desc"), ("支援に関するメモ", "support_memo"),
      ("支援が必要か", "has_support"), ("日常的支援に関するメモ", "daily_memo")
    ],
    "補助具使用・緊急時対応情報": [
      ("補助具の種類", "device_type"), ("補助具使用の有無", "in_use"),
      ("補助具に関するメモ", "device_memo"), ("緊急時対応内容", "response_info"),
      ("緊急時対応に関するメモ", "response_memo")
    ]
  };

  if (!user_data && status.type !== 'loading') {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-gray-100 p-6 text-center">
        <StatusMessage message={status.message || "データをロードできませんでした。"} type={status.type || 'error'} />
        <Button onClick={() => navigate('user_list')} color={COLORS.DARK_BUTTON} className="mt-4">
          一覧に戻る
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-gray-100 p-6">
      <h1 className={`text-3xl font-bold text-[${COLORS.PRIMARY}] mb-6 text-center`}>利用者 詳細情報</h1>

      <div className="flex-grow overflow-y-auto space-y-4">
        {status.type === 'loading' ? (
          <StatusMessage message={status.message} type={status.type} />
        ) : (
          Object.entries(allFields).map(([sectionTitle, fields]) => (
            <Card key={sectionTitle}>
              <SectionHeader>{sectionTitle}</SectionHeader>
              <div className="grid grid-cols-2 gap-4 text-sm">
                {fields.map(field => (
                  <React.Fragment key={field.id}>
                    <p className={`text-right font-semibold text-[${COLORS.SUBTEXT}]`}>{labelText}:</p>
                    <div className="text-left font-bold text-[${COLORS.TEXT}] break-words">
                      {renderFieldValue(field.id, user_data[field.id])}
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </Card>
          ))
        )}
      </div>

      <div className="mt-6 flex space-x-3">
        <Button onClick={() => navigate('user_list')} color={COLORS.DARK_BUTTON} className="flex-1">
          一覧に戻る
        </Button>
        <Button onClick={handleEdit} icon={LucideReact.Edit} className="flex-1">
          この情報を編集する
        </Button>
        <Button onClick={handleDeleteConfirm} icon={LucideReact.Trash} color={COLORS.DANGER} className="flex-1">
          この利用者を削除
        </Button>
      </div>
      <StatusMessage message={status.message} type={status.type} />
      <Modal
        show={showDeleteModal}
        title="削除の確認"
        message="本当にこの利用者を削除しますか？この操作は元に戻せません。"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  );
};


const FormScreen = ({ navigate, screenId }) => {
  const { user_data, setUserData, editing_user_id, setEditingUserId } = useContext(AppContext);
  const [formData, setFormData] = useState({});
  const [status, setStatus] = useState({ message: '', type: '' });

  // 各ステップのフィールドを定義
  const screenDefinitions = {
    'step1': {
      title: 'Step 1: 利用者情報',
      fields: {
        "基本情報": [
          { label: "名前", id: "name", type: "text" },
          { label: "年齢", id: "age", type: "number" },
          { label: "メールアドレス", id: "email_address", type: "email" },
          { label: "パスワード", id: "password", type: "password" }
        ],
        "連絡先": [
          { label: "電話番号", id: "phone", type: "tel" },
          { label: "性別", id: "gender", type: "text" },
          { label: "血液型", id: "blood_type", type: "text" },
          { label: "担当医師", id: "doctor", type: "text" }
        ],
        "顔写真": [
          { label: "顔写真", id: "photo_path_display", type: "photo_capture" } // 顔写真撮影用の特別なタイプ
        ],
        "緊急連絡先": [
          { label: "名前", id: "contact_name", type: "text" },
          { label: "続柄", id: "contact_relation", type: "text" },
          { label: "電話番号", id: "contact_phone", type: "tel" }
        ]
      },
      next: 'step2',
      prev: 'menu'
    },
    'step2': {
      title: 'Step 2: 医療情報',
      fields: {
        "持病情報": [
          { label: "病名", id: "disease_name", type: "text" },
          { label: "発症時期", id: "since_date", type: "text" }, // 実アプリでは日付ピッカーを検討
          { label: "病歴メモ", id: "disease_memo", type: "text", multiline: true }
        ],
        "アレルギー情報": [
          { label: "アレルギー名", id: "allergy_name", type: "text" },
          { label: "アレルギーに関するメモ", id: "allergy_memo", type: "text", multiline: true }
        ],
        "服用薬情報": [
          { label: "薬の名前", id: "med_name", type: "text" },
          { label: "薬の服用量", id: "dosage", type: "text" },
          { label: "服用スケジュール", id: "schedule", type: "text" },
          { label: "薬に関するメモ", id: "med_memo", type: "text", multiline: true }
        ]
      },
      next: 'step3',
      prev: 'step1'
    },
    'step3': {
      title: 'Step 3: 支援情報',
      fields: {
        "医療的支援": [
          { label: "支援内容", id: "support_desc", type: "text", multiline: true },
          { label: "支援に関するメモ", id: "support_memo", type: "text", multiline: true },
          { label: "支援が必要か", id: "has_support", type: "switch" }
        ],
        "日常的支援": [
          { label: "日常的支援に関するメモ", id: "daily_memo", type: "text", multiline: true }
        ]
      },
      next: 'step4',
      prev: 'step2'
    },
    'step4': {
      title: 'Step 4: 緊急時情報',
      fields: {
        "補助具使用": [
          { label: "補助具の種類", id: "device_type", type: "text" },
          { label: "補助具使用の有無", id: "in_use", type: "switch" },
          { label: "補助具に関するメモ", id: "device_memo", type: "text", multiline: true }
        ],
        "緊急時対応": [
          { label: "緊急時対応内容", id: "response_info", type: "text", multiline: true },
          { label: "緊急時対応に関するメモ", id: "response_memo", type: "text", multiline: true }
        ]
      },
      next: null, // 最後のステップには「次へ」がない
      prev: 'step3'
    },
  };

  const currentScreenDef = screenDefinitions[screenId];

  useEffect(() => {
    // ステップに入ったとき、またはuser_dataが変更されたとき（編集後など）にフォームを更新
    setFormData(prevData => {
        const newData = { ...prevData };
        // コンテキストから利用可能な既存のuser_dataをマージ
        Object.keys(currentScreenDef.fields).forEach(sectionKey => {
            currentScreenDef.fields[sectionKey].forEach(field => {
                const valueFromContext = user_data?.[field.id];
                if (valueFromContext !== undefined) {
                    newData[field.id] = valueFromContext;
                } else if (field.id === 'photo_path_display' && user_data?.photo_path !== undefined) {
                    newData[field.id] = user_data.photo_path; // 表示用の実際のphoto_pathを使用
                } else if (newData[field.id] === undefined) {
                    // 新しいフィールドを空文字列で初期化
                    newData[field.id] = '';
                }
            });
        });
        return newData;
    });
  }, [user_data, screenId, currentScreenDef]);


  const handleChange = (id, value) => {
    setFormData(prevData => ({ ...prevData, [id]: value }));
  };

  const handleNext = () => {
    // 現在のステップのデータをグローバルなuser_dataにマージ
    setUserData(prevUserData => ({ ...prevUserData, ...formData }));
    if (currentScreenDef.next) {
      navigate(currentScreenDef.next);
    }
  };

  const handlePrev = () => {
    // 戻る前に現在のステップのデータをグローバルなuser_dataにマージ
    setUserData(prevUserData => ({ ...prevUserData, ...formData }));
    if (currentScreenDef.prev) {
      navigate(currentScreenDef.prev);
    }
  };

  const handleSave = async () => {
    // 保存前の最終的なデータマージ
    const allData = { ...user_data, ...formData };
    setUserData(allData);

    setStatus({ message: editing_user_id ? 'データを更新中...' : 'データを保存中...', type: 'loading' });

    try {
      const url = editing_user_id ? `${API_BASE_URL}/update_user/${editing_user_id}` : `${API_BASE_URL}/register_user`;
      const method = editing_user_id ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(allData),
        signal: AbortSignal.timeout(5000),
      });

      const result = await response.json();

      if (response.ok) {
        setStatus({ message: editing_user_id ? 'データの更新に成功！' : 'データの保存に成功！', type: 'success' });
        setEditingUserId(null); // 編集状態をクリア
        if (editing_user_id) {
          navigate('detail'); // 更新後、詳細画面に戻る
        } else {
          navigate('menu'); // 新規登録後、メニューに戻る
        }
      } else {
        setStatus({ message: `エラー: ${result.message || '不明なエラー'}`, type: 'error' });
      }
    } catch (error) {
      setStatus({ message: `通信エラー: サーバーの起動が必要です。(${error.message})`, type: 'error' });
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-100 p-6">
      <h1 className={`text-3xl font-bold text-[${COLORS.PRIMARY}] mb-6 text-center`}>
        {currentScreenDef.title}
      </h1>

      <div className="flex-grow overflow-y-auto rounded-lg shadow-md bg-white p-4 space-y-4">
        {Object.entries(currentScreenDef.fields).map(([sectionTitle, fields]) => (
          <Card key={sectionTitle}>
            <SectionHeader>{sectionTitle}</SectionHeader>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
              {fields.map(field => (
                <React.Fragment key={field.id}>
                  {field.type === 'switch' ? (
                    <SwitchInput
                      label={field.label}
                      checked={formData[field.id] === 1}
                      onChange={() => handleChange(field.id, formData[field.id] === 1 ? 0 : 1)}
                    />
                  ) : field.type === 'photo_capture' ? (
                    <div className="flex flex-col col-span-full mb-4">
                      <label className={`block text-sm font-medium text-[${COLORS.SUBTEXT}] mb-1`}>{field.label}</label>
                      <div className="flex items-center space-x-2">
                        <TextInput
                          value={formData[field.id] || ''}
                          readOnly
                          placeholder="写真パス"
                          className="flex-grow"
                        />
                        <Button onClick={() => navigate('photo_capture')} icon={LucideReact.Camera}>
                          撮影
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <TextInput
                      label={field.label}
                      type={field.type}
                      value={formData[field.id] || ''}
                      onChange={(e) => handleChange(field.id, e.target.value)}
                      multiline={field.multiline}
                      password={field.type === 'password'}
                      className="col-span-full md:col-span-1" // テキスト入力の列スパンを調整
                    />
                  )}
                </React.Fragment>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-6 flex space-x-3">
        {currentScreenDef.prev && (
          <Button onClick={handlePrev} color={COLORS.DARK_BUTTON} className="flex-1" icon={LucideReact.ArrowLeft}>
            前へ
          </Button>
        )}
        {currentScreenDef.next ? (
          <Button onClick={handleNext} color={COLORS.PRIMARY} className="flex-1" icon={LucideReact.ArrowRight}>
            次へ
          </Button>
        ) : (
          <Button onClick={handleSave} color={COLORS.SUCCESS} className="flex-1" icon={LucideReact.Save}>
            保存
          </Button>
        )}
      </div>
      <StatusMessage message={status.message} type={status.type} />
    </div>
  );
};


const PhotoCaptureScreen = ({ navigate }) => {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [capturedImageBase64, setCapturedImageBase64] = useState('');
  const [displayedImageSrc, setDisplayedImageSrc] = useState(''); // Imageコンポーネントのソースを格納
  const [status, setStatus] = useState({ message: 'カメラ準備中...', type: 'loading' });
  const [faceDetectionResult, setFaceDetectionResult] = useState('');
  const [isUploading, setIsUploading] = useState(false); // アップロード中を示す新しい状態

  const { user_data, setUserData } = useContext(AppContext);

  useEffect(() => {
    let stream;
    const startCamera = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play();
          setStatus({ message: 'カメラ稼働中', type: '' });
          setFaceDetectionResult(''); // Reset messages on camera start
          setDisplayedImageSrc(''); // Clear previous image
          setCapturedImageBase64(''); // Clear previous base64
        }
      } catch (err) {
        console.error("Camera access error: ", err);
        setStatus({
          message: `カメラ起動エラー: ${err.name || err.message}。カメラへのアクセス許可を確認してください。`,
          type: 'error'
        });
      }
    };

    startCamera();

    return () => {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const capturePhoto = async () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext('2d');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageData = canvas.toDataURL('image/png'); // Get image data as base64 PNG

    setCapturedImageBase64(imageData); // ローカルで表示するためにbase64を保存
    setDisplayedImageSrc(imageData); // まずは撮影したbase64イメージを表示

    setIsUploading(true); // アップロード開始
    setStatus({ message: '写真を撮影しました。サーバーへアップロード中...', type: 'loading' });
    setFaceDetectionResult(''); // 以前の顔検出結果をクリア

    try {
      const response = await fetch(`${API_BASE_URL}/upload_photo`, { // 新しいアップロードエンドポイント
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: imageData }),
        signal: AbortSignal.timeout(30000), // アップロードのためのタイムアウトを延長
      });
      const result = await response.json();

      if (response.ok) {
        setDisplayedImageSrc(result.photo_url); // サーバーから返されたURLを表示
        setFaceDetectionResult('写真はサーバーに保存されました。');
        setStatus({ message: '写真のアップロードが完了しました。', type: 'success' });
      } else {
        setFaceDetectionResult(`写真のアップロードエラー: ${result.message || '不明なエラー'}`);
        setStatus({ message: '写真のアップロードに失敗しました。', type: 'error' });
      }
    } catch (error) {
      setFaceDetectionResult(`通信エラー: 写真アップロードAPIに接続できません。(${error.message})`);
      setStatus({ message: '写真のアップロードに失敗しました。', type: 'error' });
    } finally {
      setIsUploading(false); // アップロード終了
    }
  };

  const retakePhoto = () => {
    setCapturedImageBase64('');
    setDisplayedImageSrc('');
    setStatus({ message: 'カメラ準備中...', type: 'loading' });
    setFaceDetectionResult('');
    setIsUploading(false); // アップロード状態をリセット
    if (videoRef.current) {
      videoRef.current.play(); // 再撮影のためにビデオストリームを再開
    }
  };

  const confirmPhoto = () => {
    // displayedImageSrc がサーバーからのURLになったか、またはbase64データがあるか確認
    if (displayedImageSrc) {
      setUserData(prevUserData => ({ ...prevUserData, photo_path: displayedImageSrc })); // サーバーURLまたはbase64データを保存
      navigate('step1');
    } else {
      setStatus({ message: '写真が撮影またはアップロードされていません！', type: 'error' });
    }
  };

  const cancelCapture = () => {
    setUserData(prevUserData => ({ ...prevUserData, photo_path: '' })); // キャンセルされた場合、写真パスをクリア
    navigate('step1');
  };

  // ボタンのdisabled状態を適切に制御
  const captureButtonDisabled = isUploading || status.type === 'loading';
  const retakeButtonDisabled = isUploading || !capturedImageBase64; // 撮影済みでなければ撮り直しはできない
  const confirmButtonDisabled = isUploading || !displayedImageSrc; // アップロード済みまたは表示可能でなければ確定できない


  return (
    <div className="flex flex-col h-screen bg-gray-100 p-6">
      <h1 className={`text-3xl font-bold text-[${COLORS.PRIMARY}] mb-6 text-center`}>顔写真撮影</h1>

      <div className="flex-grow flex flex-col items-center justify-center bg-gray-200 rounded-lg overflow-hidden relative">
        {!capturedImageBase64 ? ( // 撮影前はカメラプレビュー
          <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-contain"></video>
        ) : ( // 撮影後はプレビュー画像を表示
          <img src={displayedImageSrc} alt="Captured" className="w-full h-full object-contain" />
        )}
        <canvas ref={canvasRef} style={{ display: 'none' }}></canvas> {/* 画像処理用の非表示キャンバス */}
      </div>

      <StatusMessage message={status.message} type={status.type} />
      <p className="text-center text-sm mt-1" style={{ color: status.type === 'success' ? COLORS.SUCCESS : COLORS.DANGER }}>
        {faceDetectionResult}
      </p>

      <div className="mt-6 flex space-x-3">
        {/* 撮影ボタン */}
        <Button onClick={capturePhoto} color={COLORS.PRIMARY} className="flex-1" icon={LucideReact.Camera} disabled={captureButtonDisabled}>
          撮影
        </Button>
        {/* 撮り直しボタン */}
        <Button onClick={retakePhoto} color={COLORS.DARK_BUTTON} className="flex-1" disabled={retakeButtonDisabled}>
          撮り直し
        </Button>
        {/* この写真で決定ボタン */}
        <Button onClick={confirmPhoto} color={COLORS.SUCCESS} className="flex-1" disabled={confirmButtonDisabled}>
          この写真で決定
        </Button>
        {/* キャンセルボタン */}
        <Button onClick={cancelCapture} color={COLORS.DANGER} className="flex-1" disabled={isUploading}>
          キャンセル
        </Button>
      </div>
    </div>
  );
};


// --- メインアプリコンポーネント (ルーティング) ---
function App() {
  const [currentScreen, setCurrentScreen] = useState('menu');
  const [user_data, setUserData] = useState({}); // フォームステップ用のグローバルユーザーデータ
  const [selectedUserId, setSelectedUserId] = useState(null); // DetailScreen用
  const [editingUserId, setEditingUserId] = useState(null); // 編集フロー用

  const navigate = (screenName) => {
    setCurrentScreen(screenName);
  };

  const clearUserData = () => {
    setUserData({});
    setSelectedUserId(null);
    setEditingUserId(null);
  };

  const appContextValue = {
    user_data,
    setUserData,
    selectedUserId,
    setSelectedUserId,
    editing_user_id: editingUserId,
    setEditingUserId,
    clearUserData,
  };

  let ScreenComponent;
  switch (currentScreen) {
    case 'menu':
      ScreenComponent = MenuScreen;
      break;
    case 'user_list':
      ScreenComponent = UserListScreen;
      break;
    case 'detail':
      ScreenComponent = DetailScreen;
      break;
    case 'step1':
    case 'step2':
    case 'step3':
    case 'step4':
      ScreenComponent = FormScreen;
      break;
    case 'photo_capture':
      ScreenComponent = PhotoCaptureScreen;
      break;
    default:
      ScreenComponent = MenuScreen; // フォールバック
  }

  return (
    <AppContext.Provider value={appContextValue}>
      <div className="min-h-screen font-sans antialiased" style={{ backgroundColor: COLORS.BACKGROUND }}>
        {/* 現在のスクリーンコンポーネントをレンダリング */}
        <ScreenComponent navigate={navigate} screenId={currentScreen} />
      </div>
    </AppContext.Provider>
  );
}

export default App;
