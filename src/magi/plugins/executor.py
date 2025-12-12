"""
CommandExecutor - 外部コマンドの実行

プラグインから外部ツールを実行するための機能を提供
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from magi.errors import create_plugin_error, ErrorCode, MagiException


@dataclass
class CommandResult:
    """コマンド実行結果
    
    Attributes:
        stdout: 標準出力
        stderr: 標準エラー出力
        return_code: 終了コード
        execution_time: 実行時間（秒）
    """
    stdout: str
    stderr: str
    return_code: int
    execution_time: float


class CommandExecutor:
    """外部コマンドの実行
    
    プラグインから外部ツールを実行し、結果をキャプチャする。
    タイムアウト処理も含む。
    
    Attributes:
        timeout: コマンドのタイムアウト時間（秒）
    """
    
    def __init__(self, timeout: int = 30):
        """CommandExecutorを初期化
        
        Args:
            timeout: コマンドのタイムアウト時間（秒）。デフォルトは30秒
        """
        self.timeout = timeout
    
    async def execute(
        self, 
        command: str, 
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """コマンドを実行し結果を返す
        
        Args:
            command: 実行するコマンド
            args: コマンドの引数リスト
            env: 子プロセスに渡す環境変数
            
        Returns:
            CommandResult: コマンドの実行結果
            
        Raises:
            MagiException: コマンドが見つからない場合（PLUGIN_COMMAND_FAILED）
            MagiException: タイムアウトした場合（PLUGIN_COMMAND_TIMEOUT）
        """
        if args is None:
            args = []
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)
        
        start_time = time.time()
        
        try:
            # プロセスを作成
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError:
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_COMMAND_FAILED,
                f"Command not found: {command}"
            ))
        except Exception as e:
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_COMMAND_FAILED,
                f"Failed to execute command '{command}': {e}"
            ))
        
        try:
            # タイムアウト付きで待機
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            # タイムアウト時はプロセスを終了
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass  # プロセスが既に終了している場合
            
            raise MagiException(create_plugin_error(
                ErrorCode.PLUGIN_COMMAND_TIMEOUT,
                f"Command '{command}' timed out after {self.timeout} seconds"
            ))
        
        execution_time = time.time() - start_time
        
        return CommandResult(
            stdout=stdout.decode('utf-8', errors='replace').strip(),
            stderr=stderr.decode('utf-8', errors='replace').strip(),
            return_code=process.returncode,
            execution_time=execution_time
        )
    
    def _capture_output(
        self, 
        process: asyncio.subprocess.Process
    ) -> Tuple[str, str]:
        """標準出力と標準エラーをキャプチャ
        
        Note: このメソッドは非同期executeメソッド内で使用される
                asyncio.subprocess.communicateで代替される
        
        Args:
            process: asyncioサブプロセス
            
        Returns:
            Tuple[str, str]: (stdout, stderr)のタプル
        """
        # このメソッドはexecute内のcommunicate()で代替
        # 設計上の互換性のために残しておく
        pass
